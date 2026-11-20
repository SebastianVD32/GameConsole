import unittest

from gameconsole import create_app
from gameconsole.events import MemorySink
from gameconsole.registry import MatchRegistry
from gameconsole.services import ConsoleServices

from tests.helpers import ImmediateExecutor, ScriptedEngine


class StubStats:
    configured = True

    def overview(self):
        return {"ingestion": {"totals": {"startedMatches": 1}}, "analytics": {"general": {}}, "errors": []}

    def match_result(self, match_id):
        return {"matchId": match_id, "reason": "RESIGNATION"} if match_id == "known" else None

    def health(self):
        return {"ingestion": "ok", "analytics": "ok"}


def make_client():
    services = ConsoleServices(
        registry=MatchRegistry(), sink=MemorySink(), engine=ScriptedEngine(),
        ai_executor=ImmediateExecutor(), stats=StubStats(),
    )
    app = create_app(services)
    app.config.update(TESTING=True)
    return app.test_client(), services


class PagesTest(unittest.TestCase):
    def setUp(self):
        self.client, _ = make_client()

    def test_dashboard_lists_the_three_games(self):
        html = self.client.get("/").get_data(as_text=True)
        for name in ("Ajedrez", "Pac-Man", "Juego de carreras"):
            self.assertIn(name, html)
        for path in ("/juegos/ajedrez", "/juegos/pacman", "/juegos/carreras"):
            self.assertIn(f'href="{path}"', html)
        self.assertIn('data-active-sessions', html)

    def test_menu_marks_only_the_selected_game(self):
        html = self.client.get("/juegos/pacman").get_data(as_text=True)
        self.assertIn('class="nav-link is-active" href="/juegos/pacman"', html)
        self.assertNotIn('class="nav-link is-active" href="/juegos/ajedrez"', html)

    def test_game_pages_offer_a_contextual_game_switcher(self):
        html = self.client.get("/juegos/pacman").get_data(as_text=True)
        self.assertIn('aria-label="Cambiar de juego"', html)
        for path in ("/juegos/ajedrez", "/juegos/pacman", "/juegos/carreras"):
            self.assertIn(f'href="{path}"', html)
        self.assertIn('class="game-switch amber is-active"', html)

    def test_statistics_page_has_section_navigation(self):
        html = self.client.get("/estadisticas").get_data(as_text=True)
        for anchor in ("resumen-general", "estadisticas-ajedrez", "estadisticas-arcade", "partidas-activas"):
            self.assertIn(f'href="#{anchor}"', html)
            self.assertIn(f'id="{anchor}"', html)

    def test_each_game_and_stats_page_loads(self):
        for path in ("/juegos/ajedrez", "/juegos/pacman", "/juegos/carreras", "/estadisticas"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_unknown_game_returns_custom_404(self):
        response = self.client.get("/juegos/desconocido")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Esta pantalla no existe", response.get_data(as_text=True))


class ChessApiTest(unittest.TestCase):
    def setUp(self):
        self.client, self.services = make_client()

    def create(self, **body):
        return self.client.post("/api/ajedrez/partidas", json={"name": "Ana", "color": "WHITE", **body})

    def test_create_play_and_resign(self):
        created = self.create()
        self.assertEqual(created.status_code, 201)
        state = created.get_json()
        match_id = state["matchId"]
        self.assertTrue(match_id.startswith("chess-"))
        self.assertEqual(state["players"][0]["playerId"], "jugador-ana")
        self.assertEqual(state["delivery"]["state"], "DISABLED")

        moved = self.client.post(f"/api/ajedrez/partidas/{match_id}/movimientos", json={"move": "e2e4"})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(len(moved.get_json()["history"]), 2)  # jugada humana + respuesta de la IA

        illegal = self.client.post(f"/api/ajedrez/partidas/{match_id}/movimientos", json={"move": "e4e6"})
        self.assertEqual(illegal.status_code, 409)

        resigned = self.client.post(f"/api/ajedrez/partidas/{match_id}/abandonar")
        self.assertEqual(resigned.get_json()["result"]["reason"], "RESIGNATION")

    def test_parallel_instances_have_independent_events(self):
        first = self.create().get_json()["matchId"]
        second = self.create(color="BLACK").get_json()["matchId"]
        self.assertNotEqual(first, second)
        events = self.services.sink.events
        for match_id in (first, second):
            sequences = [e["sequence"] for e in events if e["matchId"] == match_id]
            self.assertEqual(sequences, list(range(1, len(sequences) + 1)))
        listed = {item["matchId"] for item in self.client.get("/api/partidas").get_json()}
        self.assertEqual(listed, {first, second})

    def test_invalid_options_are_rejected(self):
        self.assertEqual(self.create(depth=9).status_code, 400)
        self.assertEqual(self.create(control="1+0").status_code, 400)
        self.assertEqual(self.create(color="GREEN").status_code, 400)

    def test_unknown_match(self):
        self.assertEqual(self.client.get("/api/ajedrez/partidas/nope").status_code, 404)

    def test_statistics_are_proxied_from_gamestats(self):
        self.assertEqual(self.client.get("/api/estadisticas").get_json()["ingestion"]["totals"]["startedMatches"], 1)
        self.assertEqual(self.client.get("/api/estadisticas/partidas/known").status_code, 200)
        self.assertEqual(self.client.get("/api/estadisticas/partidas/other").status_code, 404)


if __name__ == "__main__":
    unittest.main()
