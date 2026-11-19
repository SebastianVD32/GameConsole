import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app import app


class GameStatsBridgeTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_pacman_loads_real_controls_and_its_modules_only_on_its_page(self):
        html = self.client.get('/juegos/pacman').get_data(as_text=True)
        self.assertIn('id="pacman-board"', html)
        self.assertIn('js/pacman-engine.js', html)
        self.assertNotIn('Datos de muestra', html)
        self.assertNotIn('js/pacman-engine.js', self.client.get('/juegos/ajedrez').get_data(as_text=True))

    @patch('gamestats.urlopen')
    def test_event_is_forwarded_without_changing_the_contract(self, urlopen):
        payload = dict(gameId='PACMAN', eventId='one', sequence=1, data={})
        urlopen.return_value.__enter__.return_value = io.StringIO('{"accepted":true}')
        urlopen.return_value.__enter__.return_value.status = 201
        result = self.client.post('/api/gamestats/events', json=payload)
        self.assertEqual(result.status_code, 201)
        sent = urlopen.call_args.args[0]
        self.assertEqual(json.loads(sent.data), payload)
        self.assertTrue(sent.full_url.endswith('/api/v1/events'))

    @patch('gamestats.urlopen', side_effect=URLError('offline'))
    def test_service_outage_is_reported(self, _urlopen):
        result = self.client.post('/api/gamestats/events', json={'gameId': 'PACMAN'})
        self.assertEqual(result.status_code, 503)

    @patch('gamestats.urlopen')
    def test_upstream_validation_code_is_preserved_for_the_queue(self, urlopen):
        urlopen.side_effect = HTTPError('http://localhost', 409, 'Conflict', {}, io.BytesIO(b'{"code":"DUPLICATE_EVENT"}'))
        result = self.client.post('/api/gamestats/events', json={'gameId': 'PACMAN'})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json['code'], 'DUPLICATE_EVENT')

    @patch('gamestats.urlopen')
    def test_statistics_are_forwarded_from_scala_without_local_calculation(self, urlopen):
        data = {'playerId': 'p1', 'completedMatches': 8, 'totalScore': 1234, 'bestScore': 300}
        urlopen.return_value.__enter__.return_value = io.StringIO(json.dumps(data))
        urlopen.return_value.__enter__.return_value.status = 200
        self.assertEqual(self.client.get('/api/gamestats/pacman/players/p1').json, data)
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith('/api/v1/pacman/players/p1'))

    def test_invalid_payload_is_rejected(self):
        self.assertEqual(self.client.post('/api/gamestats/events', json=[]).status_code, 400)
        self.assertEqual(self.client.post('/api/gamestats/events', json={'gameId': 'CHESS'}).status_code, 400)

    def test_racing_loads_its_own_canvas_and_modules(self):
        html = self.client.get('/juegos/carreras').get_data(as_text=True)
        self.assertIn('id="racing-board"', html)
        self.assertIn('js/racing-engine.js', html)
        self.assertNotIn('de demostración', html)
        self.assertNotIn('js/pacman-engine.js', html)

    @patch('gamestats.urlopen')
    def test_racing_events_share_the_bridge_without_changing_the_envelope(self, urlopen):
        event = dict(gameId='RACING', type='MATCH_STARTED', data={'driverIds': ['p', 'ai'], 'plannedLaps': 3})
        urlopen.return_value.__enter__.return_value = io.StringIO('{"accepted":true}')
        urlopen.return_value.__enter__.return_value.status = 201
        self.assertEqual(self.client.post('/api/gamestats/events', json=event).status_code, 201)
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), event)

    @patch('gamestats.urlopen')
    def test_race_result_is_queried_from_scala_without_recalculating_it(self, urlopen):
        data = {'gameId': 'RACING', 'matchId': 'race-one', 'drivers': [{'playerId': 'p', 'bestLapTimeMs': 32100, 'finalPosition': 2}]}
        urlopen.return_value.__enter__.return_value = io.StringIO(json.dumps(data))
        urlopen.return_value.__enter__.return_value.status = 200
        self.assertEqual(self.client.get('/api/gamestats/matches/race-one').json, data)
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith('/api/v1/matches/race-one'))


if __name__ == '__main__':
    unittest.main()
