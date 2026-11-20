import copy
import tempfile
import threading
import unittest
from pathlib import Path

from gameconsole.arcade import ArcadeRelay, EventConflict
from gameconsole.events.dispatcher import TransportError, TransportResponse
from tests.test_app import make_client


def event(sequence=1, match='pac-one', game='PACMAN'):
    return dict(eventId=f'{match}-{sequence}', timestamp='2026-11-19T12:00:00.000Z',
                gameId=game, gameVersion='1.0', matchId=match, sequence=sequence,
                playerId=None if sequence == 1 else 'p',
                type='MATCH_STARTED' if sequence == 1 else 'PELLET_EATEN',
                data={'playerId': 'p', 'initialLevel': 1, 'initialLives': 3} if sequence == 1 else {'level': 1, 'pelletId': f'cell-{sequence}'})


class AcceptTransport:
    def __init__(self):
        self.events = []

    def post_event(self, payload):
        self.events.append(payload)
        return TransportResponse(201, {'accepted': True})


class ArcadeRelayTest(unittest.TestCase):
    def setUp(self):
        self.transport = AcceptTransport()
        self.relay = ArcadeRelay(':memory:', self.transport, auto_start=False)
        self.addCleanup(self.relay.close)

    def test_received_events_are_committed_before_network_delivery(self):
        result = self.relay.append(event())
        self.assertTrue(result['persisted'])
        self.assertEqual(self.transport.events, [])
        self.assertEqual(self.relay.status('pac-one')['pending'], 1)
        self.relay.drain('pac-one')
        self.assertEqual(self.relay.status('pac-one')['delivered'], 1)

    def test_ids_and_payloads_are_preserved_and_identical_retries_are_idempotent(self):
        source = event()
        self.relay.append(source)
        self.relay.append(copy.deepcopy(source))
        self.assertEqual(self.relay.history('pac-one'), [source])
        changed = {**source, 'data': {'different': True}}
        with self.assertRaises(EventConflict):
            self.relay.append(changed)
        self.relay.drain('pac-one')
        self.assertEqual(self.transport.events, [source])

    def test_gap_and_post_finish_actions_are_rejected(self):
        with self.assertRaises(ValueError):
            self.relay.append(event(2))
        self.relay.append(event())
        with self.assertRaises(EventConflict):
            self.relay.append(event(3))
        finish = {**event(2), 'type': 'MATCH_FINISHED', 'playerId': None, 'data': {'score': 0, 'reason': 'QUIT'}}
        self.relay.append(finish)
        with self.assertRaises(EventConflict):
            self.relay.append(event(3))

    def test_batch_is_atomic_when_a_later_event_conflicts(self):
        with self.assertRaises(EventConflict):
            self.relay.append_batch([event(), event(3)])
        self.assertIsNone(self.relay.status('pac-one'))
        self.assertEqual(self.relay.history('pac-one'), [])

    def test_utc_chronology_and_exact_envelope_are_enforced(self):
        for wrong in [{**event(), 'extra': 'field'}, {**event(), 'timestamp': '2026-11-19T12:00:00-06:00'},
                      {**event(), 'sequence': True}, {**event(), 'playerId': 'p'}]:
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.relay.append(wrong)
        self.relay.append(event())
        with self.assertRaises(ValueError):
            self.relay.append({**event(2), 'timestamp': '2026-11-18T12:00:00Z'})

    def test_outage_and_service_restart_recover_from_the_durable_journal(self):
        class Offline:
            def post_event(self, payload):
                raise TransportError('offline')
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'events.sqlite3')
            original = ArcadeRelay(path, Offline(), auto_start=False)
            original.append_batch([event(), event(2)])
            original.drain('pac-one')
            self.assertEqual(original.status('pac-one')['state'], 'RETRYING')
            original.close()
            recovered = ArcadeRelay(path, self.transport, auto_start=False)
            try:
                self.assertEqual(recovered.status('pac-one')['pending'], 2)
                recovered.retry('pac-one')
                recovered.drain('pac-one')
                self.assertEqual(self.transport.events, [event(), event(2)])
                self.assertEqual(recovered.status('pac-one')['state'], 'DELIVERED')
            finally:
                recovered.close()

    def test_go_losing_state_replays_the_original_history_without_new_ids(self):
        class Restarted(AcceptTransport):
            forgot = False
            def post_event(self, payload):
                if self.forgot and payload['sequence'] != 1:
                    self.forgot = False
                    return TransportResponse(422, {'message': 'Debe comenzar con MATCH_STARTED'})
                return super().post_event(payload)
        transport = Restarted()
        relay = ArcadeRelay(':memory:', transport, auto_start=False)
        self.addCleanup(relay.close)
        relay.append(event()); relay.drain('pac-one')
        transport.forgot = True
        relay.append(event(2)); relay.drain('pac-one')
        self.assertEqual(transport.events, [event(), event(), event(2)])
        self.assertEqual(relay.status('pac-one')['resyncs'], 1)

    def test_only_explicit_duplicate_event_acknowledgments_are_accepted(self):
        class Conflict:
            def __init__(self, code): self.code = code
            def post_event(self, payload): return TransportResponse(409, {'code': self.code})
        for code, state in [('DUPLICATE_EVENT', 'DELIVERED'), ('OTHER_CONFLICT', 'REJECTED')]:
            relay = ArcadeRelay(':memory:', Conflict(code), auto_start=False)
            try:
                relay.append(event()); relay.drain('pac-one')
                self.assertEqual(relay.status('pac-one')['state'], state)
            finally:
                relay.close()

    def test_slow_match_does_not_block_other_matches(self):
        started, release, fast = threading.Event(), threading.Event(), threading.Event()
        class Slow:
            def post_event(self, payload):
                if payload['matchId'] == 'slow':
                    started.set(); release.wait(3)
                else:
                    fast.set()
                return TransportResponse(201, {'accepted': True})
        relay = ArcadeRelay(':memory:', Slow(), workers=2)
        try:
            relay.append(event(match='slow'))
            self.assertTrue(started.wait(2))
            relay.append(event(match='fast'))
            self.assertTrue(fast.wait(2))
        finally:
            release.set(); relay.close()


class ArcadeApiTest(unittest.TestCase):
    def setUp(self):
        self.client, _ = make_client()
        self.relay = self.client.application.extensions['arcade']
        self.addCleanup(self.relay.close)

    def test_endpoint_acknowledges_durable_storage_even_without_gamestats(self):
        response = self.client.post('/api/arcade/events', json=event())
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json['persisted'])
        self.assertEqual(self.client.get('/api/arcade/partidas/pac-one/envio').json['pending'], 1)

    def test_closing_batch_and_duplicate_single_request_do_not_duplicate_events(self):
        self.assertEqual(self.client.post('/api/arcade/events/batch', json=[event(), event(2)]).status_code, 202)
        self.assertEqual(self.client.post('/api/arcade/events', json=event(2)).status_code, 202)
        self.assertEqual(len(self.relay.history('pac-one')), 2)

    def test_console_registers_both_arcade_games_without_calculating_statistics(self):
        self.client.post('/api/arcade/events', json=event())
        race = {**event(match='race-one', game='RACING'), 'data': {'driverIds': ['p', 'ai'], 'plannedLaps': 3}}
        self.client.post('/api/arcade/events', json=race)
        sessions = self.client.get('/api/partidas').json
        self.assertEqual({s['slug'] for s in sessions}, {'pacman', 'carreras'})
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('Instancia arcade iniciada', html)
        self.assertNotIn('?partida=pac-one', html)  # no misleading control link to another tab's state
        self.assertEqual(self.client.get('/api/estadisticas').json['ingestion']['totals']['startedMatches'], 1)  # supplied by StubStats

    def test_invalid_envelope_and_unknown_delivery_are_reported(self):
        self.assertEqual(self.client.post('/api/arcade/events', json={}).status_code, 400)
        self.assertEqual(self.client.get('/api/arcade/partidas/unknown/envio').status_code, 404)
        self.assertEqual(self.client.post('/api/arcade/partidas/unknown/reintentar').status_code, 404)

    def test_race_abort_is_terminal_and_retries_preserve_the_same_event(self):
        start = {**event(match='race-abort', game='RACING'), 'data': {'driverIds': ['p', 'ai'], 'plannedLaps': 3}}
        abort = {**event(2, match='race-abort', game='RACING'), 'type': 'MATCH_ABORTED',
                 'playerId': None, 'data': {'reason': 'USER_QUIT'}}
        self.assertEqual(self.client.post('/api/arcade/events/batch', json=[start, abort]).status_code, 202)
        self.assertEqual(self.client.post('/api/arcade/events', json=abort).status_code, 202)
        self.assertEqual(self.relay.history('race-abort'), [start, abort])
        session = next(s for s in self.client.get('/api/partidas').json if s['matchId'] == 'race-abort')
        self.assertTrue(session['finished'])
        self.assertEqual(session['status'], 'Abortada')
        late = {**abort, 'eventId': 'late', 'sequence': 3}
        self.assertEqual(self.client.post('/api/arcade/events', json=late).status_code, 409)


if __name__ == '__main__':
    unittest.main()
