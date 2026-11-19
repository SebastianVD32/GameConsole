import unittest

from gameconsole.events import ChessEvents, EventStream, MemorySink
from gameconsole.games.chess import ChessMatch, Color, ComputerPlayer, HumanPlayer, MatchError, TimeControl

from tests.helpers import FakeClock, ImmediateExecutor, ScriptedEngine


def build(human_color=Color.WHITE, script=None, control=TimeControl(60_000, 1_000)):
    sink = MemorySink()
    clock = FakeClock()
    engine = ScriptedEngine(script)
    human = HumanPlayer("jugador-ana", "Ana", human_color)
    computer = ComputerPlayer("ia-prolog-n2", "IA", human_color.opponent, engine, 2)
    match = ChessMatch("chess-test", human, computer, control,
                       ChessEvents(EventStream("CHESS", "1.0", "chess-test", sink)), ImmediateExecutor(), clock)
    return match, sink, clock, engine


def assert_gamestats_contract(test, events):
    """Reproduce las reglas que valida el servicio Go de GameStats para CHESS."""
    test.assertEqual(events[0]["type"], "MATCH_STARTED")
    start = events[0]["data"]
    colors = {p["playerId"]: p["color"] for p in start["participants"]}
    clocks = {pid: start["initialClockMs"] for pid in colors}
    move_owner, next_move = {}, 1
    for index, event in enumerate(events, start=1):
        test.assertEqual(event["sequence"], index)
        if event["type"] == "AI_DECISION":
            test.assertEqual(event["data"]["moveNumber"], next_move)
        elif event["type"] == "MOVE_PLAYED":
            data = event["data"]
            test.assertEqual(data["moveNumber"], next_move)
            test.assertEqual(colors[event["playerId"]], "WHITE" if next_move % 2 else "BLACK")
            test.assertEqual(data["clockBeforeMs"], clocks[event["playerId"]])
            test.assertEqual(data["clockAfterMs"], data["clockBeforeMs"] - data["decisionTimeMs"] + start["incrementMs"])
            clocks[event["playerId"]] = data["clockAfterMs"]
            move_owner[event["eventId"]] = event["playerId"]
            next_move += 1
        elif event["type"] == "PIECE_CAPTURED":
            test.assertEqual(move_owner[event["data"]["moveEventId"]], event["playerId"])
            test.assertNotEqual(event["data"]["capturedPiece"], "KING")
    test.assertEqual(events[-1]["type"], "MATCH_FINISHED")


class ChessMatchTest(unittest.TestCase):
    def test_fools_mate_produces_valid_event_stream(self):
        match, sink, clock, engine = build(script=["e7e5", "d8h4"])
        match.start()
        clock.advance(2)
        match.play_human_move("f2f3")
        clock.advance(1)
        match.play_human_move("g2g4")
        self.assertTrue(match.is_finished)
        self.assertEqual(match.result.reason, "CHECKMATE")
        self.assertEqual(match.result.winner.player_id, "ia-prolog-n2")
        types = [e["type"] for e in sink.events]
        self.assertEqual(types, ["MATCH_STARTED", "MOVE_PLAYED", "AI_DECISION", "MOVE_PLAYED", "MOVE_PLAYED",
                                 "AI_DECISION", "MOVE_PLAYED", "MATCH_FINISHED"])
        self.assertEqual(sink.events[-1]["data"], {"winnerPlayerId": "ia-prolog-n2", "reason": "CHECKMATE"})
        self.assertEqual(sink.events[1]["data"]["decisionTimeMs"], 2000)
        assert_gamestats_contract(self, sink.events)

    def test_computer_moves_first_when_human_plays_black(self):
        match, sink, _, engine = build(human_color=Color.BLACK, script=["e2e4"])
        match.start()
        self.assertEqual(engine.calls, 1)
        self.assertEqual(match.snapshot()["turn"], "BLACK")
        self.assertEqual(sink.events[1]["type"], "AI_DECISION")
        self.assertEqual(sink.events[1]["data"]["nodesEvaluated"], 345)

    def test_capture_emits_piece_captured_linked_to_move(self):
        match, sink, _, _ = build(script=["d7d5", "a7a6"])
        match.start()
        match.play_human_move("e2e4")
        match.play_human_move("e4d5")
        capture = next(e for e in sink.events if e["type"] == "PIECE_CAPTURED")
        self.assertEqual(capture["data"]["capturedPiece"], "PAWN")
        self.assertEqual(capture["data"]["capturedPlayerId"], "ia-prolog-n2")
        assert_gamestats_contract(self, sink.events + [{"type": "MATCH_FINISHED", "sequence": len(sink.events) + 1}])

    def test_rejects_illegal_and_out_of_turn_moves(self):
        match, _, _, _ = build(human_color=Color.BLACK, script=["e2e4"])
        match.start()
        with self.assertRaises(MatchError):
            match.play_human_move("e7e4")
        match2, _, _, _ = build()
        match2.start()
        with self.assertRaises(MatchError):
            match2.play_human_move("e7e5")

    def test_resignation(self):
        match, sink, _, _ = build()
        match.start()
        match.resign()
        self.assertEqual(sink.events[-1]["data"], {"winnerPlayerId": "ia-prolog-n2", "reason": "RESIGNATION"})
        with self.assertRaises(MatchError):
            match.play_human_move("e2e4")

    def test_timeout_is_detected_by_tick(self):
        match, sink, clock, _ = build(control=TimeControl(5_000, 0))
        match.start()
        clock.advance(6)
        match.tick()
        self.assertEqual(match.result.reason, "TIMEOUT")
        self.assertEqual(sink.events[-1]["data"]["winnerPlayerId"], "ia-prolog-n2")
        self.assertEqual([e["type"] for e in sink.events].count("MATCH_FINISHED"), 1)

    def test_snapshot_exposes_legal_moves_only_on_human_turn(self):
        match, _, _, _ = build()
        match.start()
        snapshot = match.snapshot()
        self.assertEqual(len(snapshot["legalMoves"]), 20)
        self.assertEqual(snapshot["orientation"], "WHITE")
        self.assertEqual(len(snapshot["board"]), 64)


if __name__ == "__main__":
    unittest.main()
