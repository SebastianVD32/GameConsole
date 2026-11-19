import unittest

from gameconsole.games.chess.board import Board, IllegalMoveError
from gameconsole.games.chess.clock import ChessClock, TimeControl
from gameconsole.games.chess.moves import Move
from gameconsole.games.chess.notation import to_san
from gameconsole.games.chess.pieces import Color

from tests.helpers import FakeClock

# Posiciones de referencia y conteos perft publicados (chessprogramming.org).
PERFT_CASES = [
    ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 3, 8902),
    ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 2, 2039),
    ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 3, 2812),
    ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3, 9467),
    ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 2, 1486),
]


def perft(board: Board, depth: int) -> int:
    if depth == 0:
        return 1
    total = 0
    for move in board.legal_moves():
        child = board.copy()
        child.play(move)
        total += perft(child, depth - 1)
    return total


class PerftTest(unittest.TestCase):
    def test_reference_positions(self):
        for fen, depth, expected in PERFT_CASES:
            with self.subTest(fen=fen):
                self.assertEqual(perft(Board.from_fen(fen), depth), expected)

    def test_fen_round_trip(self):
        for fen, _, _ in PERFT_CASES:
            self.assertEqual(Board.from_fen(fen).fen(), fen)


class SpecialMovesTest(unittest.TestCase):
    def test_castling_moves_rook_and_removes_rights(self):
        board = Board.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        outcome = board.play(Move.from_uci("e1g1"))
        self.assertTrue(outcome.is_castling)
        self.assertEqual(board.fen().split()[0], "r3k2r/8/8/8/8/8/8/R4RK1")
        self.assertEqual(board.castling.fen, "kq")

    def test_cannot_castle_through_attacked_square(self):
        board = Board.from_fen("4kr2/8/8/8/8/8/8/R3K2R w KQ - 0 1")  # torre negra ataca f1
        self.assertNotIn("e1g1", {m.uci for m in board.legal_moves()})
        self.assertIn("e1c1", {m.uci for m in board.legal_moves()})

    def test_en_passant_removes_captured_pawn(self):
        board = Board.from_fen("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        outcome = board.play(Move.from_uci("e5d6"))
        self.assertTrue(outcome.is_en_passant)
        self.assertEqual(outcome.captured.kind, "PAWN")
        self.assertIsNone(board.piece_at(35))  # d5 vacío

    def test_promotion_creates_chosen_piece(self):
        board = Board.from_fen("8/4P3/8/8/8/k7/8/4K3 w - - 0 1")
        outcome = board.play(Move.from_uci("e7e8n"))
        self.assertEqual(outcome.piece.kind, "PAWN")
        self.assertEqual(outcome.promoted_to.kind, "KNIGHT")

    def test_pinned_piece_cannot_move(self):
        board = Board.from_fen("4r1k1/8/8/8/8/8/4N3/4K3 w - - 0 1")
        self.assertFalse(any(m.origin == 12 for m in board.legal_moves()))

    def test_illegal_move_is_rejected(self):
        with self.assertRaises(IllegalMoveError):
            Board.initial().play(Move.from_uci("e2e5"))


class NotationTest(unittest.TestCase):
    def test_san_examples(self):
        self.assertEqual(to_san(Board.initial(), Move.from_uci("g1f3")), "Nf3")
        self.assertEqual(to_san(Board.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"), Move.from_uci("e1c1")), "O-O-O")
        self.assertEqual(to_san(Board.from_fen("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"), Move.from_uci("e5d6")), "exd6")
        self.assertEqual(to_san(Board.from_fen("8/4P3/8/8/8/k7/8/4K3 w - - 0 1"), Move.from_uci("e7e8q")), "e8=Q")
        mate = Board.from_fen("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
        self.assertEqual(to_san(mate, Move.from_uci("a1a8")), "Ra8#")

    def test_disambiguation(self):
        board = Board.from_fen("4k3/8/8/8/8/8/8/R4RK1 w - - 0 1")
        self.assertEqual(to_san(board, Move.from_uci("a1d1")), "Rad1")
        board = Board.from_fen("4k3/8/8/R7/8/8/8/R5K1 w - - 0 1")
        self.assertEqual(to_san(board, Move.from_uci("a1a3")), "R1a3")


class EndgameRulesTest(unittest.TestCase):
    def test_insufficient_material(self):
        self.assertTrue(Board.from_fen("4k3/8/8/8/8/8/8/4KB2 w - - 0 1").has_insufficient_material())
        self.assertFalse(Board.from_fen("4k3/8/8/8/8/8/8/4KR2 w - - 0 1").has_insufficient_material())


class ClockTest(unittest.TestCase):
    def test_reading_follows_gamestats_formula(self):
        now = FakeClock()
        clock = ChessClock(TimeControl(60_000, 2_000), now)
        clock.start(Color.WHITE)
        now.advance(1.5)
        reading = clock.complete_turn()
        self.assertEqual((reading.before_ms, reading.decision_ms, reading.after_ms), (60_000, 1_500, 60_500))
        self.assertEqual(reading.after_ms, reading.before_ms - reading.decision_ms + 2_000)

    def test_flag_when_time_runs_out(self):
        now = FakeClock()
        clock = ChessClock(TimeControl(1_000, 0), now)
        clock.start(Color.BLACK)
        now.advance(1.0)
        self.assertIs(clock.flagged(), Color.BLACK)
        with self.assertRaises(TimeoutError):
            clock.complete_turn()


if __name__ == "__main__":
    unittest.main()
