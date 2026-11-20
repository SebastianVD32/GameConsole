import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from gameconsole.events import (
    ChessEvents,
    EventDispatcher,
    EventStream,
    MemorySink,
    PacmanEvents,
    RacingEvents,
    RetryPolicy,
    TransportError,
    TransportResponse,
)

ENVELOPE = ["eventId", "timestamp", "gameId", "gameVersion", "matchId", "sequence", "playerId", "type", "data"]
FAST = RetryPolicy(attempts=3, base_delay=0, max_delay=0, pause=0.01)


class EventStreamTest(unittest.TestCase):
    def test_envelope_sequence_and_unique_ids(self):
        sink = MemorySink()
        events = ChessEvents(EventStream("CHESS", "1.0", "m-1", sink))
        events.match_started([("a", "WHITE"), ("b", "BLACK")], 60_000, 0)
        events.move_played("a", 1, "PAWN", "e2", "e4", 10, 60_000, 59_990)
        events.match_finished(None, "DRAW")
        self.assertEqual([e["sequence"] for e in sink.events], [1, 2, 3])
        self.assertEqual(len({e["eventId"] for e in sink.events}), 3)
        for event in sink.events:
            self.assertEqual(list(event), ENVELOPE)
            self.assertTrue(event["timestamp"].endswith("Z"))
        self.assertIsNone(sink.events[0]["playerId"])
        self.assertIsNone(sink.events[-1]["playerId"])

    def test_timestamps_never_go_backwards(self):
        base = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        moments = iter([base, base - timedelta(seconds=5), base + timedelta(seconds=1)])
        sink = MemorySink()
        stream = EventStream("PACMAN", "1.0", "p-1", sink, now=lambda: next(moments))
        for _ in range(3):
            stream.emit("X", "p", {})
        stamps = [e["timestamp"] for e in sink.events]
        self.assertEqual(stamps, sorted(stamps))

    def test_recorder_rejects_foreign_stream(self):
        with self.assertRaises(ValueError):
            PacmanEvents(EventStream("CHESS", "1.0", "m", MemorySink()))

    def test_pacman_and_racing_payloads_match_contract(self):
        sink = MemorySink()
        pac = PacmanEvents(EventStream("PACMAN", "1.0", "p", sink))
        pac.match_started("p1")
        power = pac.power_up_collected("p1", 1, "pp-1", 8000)
        pac.ghost_eaten("p1", 1, "BLINKY", power["eventId"])
        pac.match_finished(250, "GAME_OVER")
        self.assertEqual(sink.events[0]["data"], {"playerId": "p1", "initialLevel": 1, "initialLives": 3})
        self.assertEqual(sink.events[2]["data"]["powerUpEventId"], power["eventId"])

        race_sink = MemorySink()
        race = RacingEvents(EventStream("RACING", "1.0", "r", race_sink))
        race.match_started(["d1", "d2"], 3)
        race.lap_completed("d1", 1, 81_000, 1)
        race.match_finished([("d1", 1), ("d2", 2)])
        self.assertEqual(race_sink.events[0]["data"], {"driverIds": ["d1", "d2"], "plannedLaps": 3})
        self.assertEqual(race_sink.events[-1]["data"]["classification"][1], {"playerId": "d2", "position": 2})


    def test_racing_abort_payload_and_reason_validation(self):
        sink = MemorySink()
        race = RacingEvents(EventStream("RACING", "1.0", "abort", sink))
        for reason in ("USER_QUIT", "RESTARTED", "PAGE_CLOSED"):
            result = race.match_aborted(reason)
            self.assertEqual(result["type"], "MATCH_ABORTED")
            self.assertIsNone(result["playerId"])
            self.assertEqual(result["data"], {"reason": reason})
        with self.assertRaises(ValueError):
            race.match_aborted("OTHER")
        self.assertEqual(len(sink.events), 3)


class RecordingTransport:
    def __init__(self, responses=None, delay_for=None):
        self.received: list[dict] = []
        self._responses = responses or {}
        self._delay_for = delay_for or {}
        self._lock = threading.Lock()

    def post_event(self, event):
        time.sleep(self._delay_for.get(event["matchId"], 0))
        script = self._responses.get(event["eventId"])
        if script:
            outcome = script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome != 201:
                return TransportResponse(outcome, {"message": "rechazado"})
        with self._lock:
            self.received.append(event)
        return TransportResponse(201, {})


def make_events(match_id, count):
    return [{"eventId": f"{match_id}-{i}", "matchId": match_id, "gameId": "CHESS", "type": "T", "sequence": i}
            for i in range(1, count + 1)]


class DispatcherTest(unittest.TestCase):
    def test_keeps_order_within_each_match(self):
        transport = RecordingTransport()
        dispatcher = EventDispatcher(transport, max_workers=4, retry=FAST)
        batches = [make_events(f"m{n}", 30) for n in range(5)]
        for i in range(30):  # intercalados, como partidas concurrentes
            for batch in batches:
                dispatcher.submit(batch[i])
        self.assertTrue(dispatcher.flush(5))
        for n in range(5):
            sequence = [e["sequence"] for e in transport.received if e["matchId"] == f"m{n}"]
            self.assertEqual(sequence, list(range(1, 31)))
        dispatcher.shutdown()

    def test_slow_match_does_not_block_others(self):
        transport = RecordingTransport(delay_for={"slow": 0.5})
        dispatcher = EventDispatcher(transport, max_workers=4, retry=FAST)
        dispatcher.submit(make_events("slow", 1)[0])
        started = time.monotonic()
        for event in make_events("fast", 5):
            dispatcher.submit(event)
        while len([e for e in transport.received if e["matchId"] == "fast"]) < 5:
            self.assertLess(time.monotonic() - started, 0.4, "la partida rápida quedó bloqueada")
            time.sleep(0.01)
        dispatcher.flush(5)
        dispatcher.shutdown()

    def test_retries_network_failures_and_treats_409_as_delivered(self):
        events = make_events("m", 3)
        transport = RecordingTransport(responses={
            "m-1": [TransportError("caído"), TransportError("caído"), 201],
            "m-2": [409],
        })
        dispatcher = EventDispatcher(transport, retry=FAST)
        for event in events:
            dispatcher.submit(event)
        self.assertTrue(dispatcher.flush(5))
        status = dispatcher.status("m")
        self.assertEqual(status["delivered"], 3)
        self.assertEqual(status["duplicates"], 1)
        self.assertGreaterEqual(status["retries"], 2)
        self.assertEqual(status["state"], "OK")
        dispatcher.shutdown()

    def test_queue_pauses_and_resumes_when_gamestats_is_down(self):
        events = make_events("m", 2)
        transport = RecordingTransport(responses={"m-1": [TransportError("x")] * 4 + [201]})
        dispatcher = EventDispatcher(transport, retry=FAST)
        for event in events:
            dispatcher.submit(event)
        self.assertTrue(dispatcher.flush(5))
        self.assertEqual([e["eventId"] for e in transport.received], ["m-1", "m-2"])
        dispatcher.shutdown()

    def test_resends_history_when_gamestats_forgot_the_match(self):
        class RestartedGameStats:
            """Acepta m-1 y m-2, se "reinicia" y exige de nuevo MATCH_STARTED."""
            def __init__(self):
                self.known, self.restarted, self.received = set(), False, []

            def post_event(self, event):
                if event["eventId"] == "m-3" and not self.restarted:
                    self.restarted, self.known = True, set()
                if event["sequence"] != 1 and "m" not in self.known:
                    return TransportResponse(422, {"message": "evento rechazado: la primera accion de una partida debe ser MATCH_STARTED"})
                self.known.add("m")
                self.received.append(event["eventId"])
                return TransportResponse(201, {})

        transport = RestartedGameStats()
        dispatcher = EventDispatcher(transport, retry=FAST)
        for event in make_events("m", 4):
            dispatcher.submit(event)
        self.assertTrue(dispatcher.flush(5))
        self.assertEqual(transport.received, ["m-1", "m-2", "m-1", "m-2", "m-3", "m-4"])
        self.assertEqual(dispatcher.status("m")["resyncs"], 1)
        self.assertEqual(dispatcher.status("m")["state"], "OK")
        dispatcher.shutdown()

    def test_contract_rejection_stops_that_match_only(self):
        transport = RecordingTransport(responses={"bad-2": [422]})
        dispatcher = EventDispatcher(transport, retry=FAST)
        for event in make_events("bad", 3) + make_events("good", 2):
            dispatcher.submit(event)
        dispatcher.flush(2)
        self.assertEqual(dispatcher.status("bad")["state"], "REJECTED")
        self.assertEqual(dispatcher.status("bad")["pending"], 2)
        self.assertEqual(dispatcher.status("good")["delivered"], 2)
        dispatcher.shutdown()


if __name__ == "__main__":
    unittest.main()
