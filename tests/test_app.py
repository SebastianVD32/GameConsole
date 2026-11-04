import unittest

from app import app


class GameConsoleRoutesTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_dashboard_loads_the_three_games(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Ajedrez", html)
        self.assertIn("Pac-Man", html)
        self.assertIn("Juego de carreras", html)

    def test_each_game_route_loads(self):
        for game_id in ("ajedrez", "pacman", "carreras"):
            with self.subTest(game_id=game_id):
                response = self.client.get(f"/juegos/{game_id}")
                self.assertEqual(response.status_code, 200)

    def test_chess_demo_renders_a_complete_board(self):
        response = self.client.get("/juegos/ajedrez")
        self.assertEqual(response.get_data(as_text=True).count('class="square"'), 64)

    def test_unknown_game_returns_custom_404(self):
        response = self.client.get("/juegos/desconocido")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Esta pantalla no existe", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
