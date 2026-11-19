import unittest

from gameconsole.games.chess.board import Board
from gameconsole.games.chess.moves import Move

try:
    import janus_swi  # noqa: F401
    from gameconsole.games.chess.ai.engine import PrologChessEngine

    ENGINE = PrologChessEngine()
    ENGINE.warm_up()
except Exception as error:  # pragma: no cover - entorno sin SWI-Prolog
    ENGINE = None
    REASON = str(error)
else:
    REASON = ""

from tests.test_chess_rules import PERFT_CASES


@unittest.skipIf(ENGINE is None, f"SWI-Prolog/janus no disponible: {REASON}")
class PrologEngineTest(unittest.TestCase):
    def test_prolog_perft_matches_reference(self):
        import janus_swi as janus
        for fen, depth, expected in PERFT_CASES:
            with self.subTest(fen=fen):
                count = janus.query_once("chess_ai:perft(F, D, N)", {"F": fen, "D": depth})["N"]
                self.assertEqual(count, expected)

    def test_prolog_and_python_agree_on_legal_moves(self):
        positions = [fen for fen, _, _ in PERFT_CASES] + [
            "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
            "4kr2/8/8/8/8/8/8/R3K2R w KQ - 0 1",
        ]
        for fen in positions:
            board = Board.from_fen(fen)
            with self.subTest(fen=fen):
                self.assertEqual(sorted(ENGINE.legal_moves(board)), sorted(m.uci for m in board.legal_moves()))

    def test_finds_mate_in_one(self):
        board = Board.from_fen("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
        decision = ENGINE.choose_move(board, 2)
        self.assertEqual(decision.move, Move.from_uci("a1a8"))
        self.assertGreater(decision.score, 90_000)

    def test_finds_scholars_mate(self):
        board = Board.from_fen("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
        self.assertEqual(ENGINE.choose_move(board, 2).move.uci, "h5f7")

    def test_captures_hanging_queen(self):
        board = Board.from_fen("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1")
        self.assertEqual(ENGINE.choose_move(board, 2).move.uci, "d2d5")

    def test_avoids_losing_its_queen(self):
        # La dama negra está atacada por un peón; la IA debe moverla.
        board = Board.from_fen("rnb1kbnr/pppp1ppp/8/4p3/3q4/2P5/PP1PPPPP/RNBQKBNR b KQkq - 0 3")
        decision = ENGINE.choose_move(board, 2)
        self.assertEqual(decision.move.origin, 27)  # d4
        self.assertGreater(decision.nodes, 0)

    def test_black_promotes(self):
        board = Board.from_fen("8/8/8/8/8/K7/4p3/7k b - - 0 1")
        self.assertEqual(ENGINE.choose_move(board, 2).move.uci, "e2e1q")


if __name__ == "__main__":
    unittest.main()
