"""Dobles de prueba compartidos."""

from __future__ import annotations

from concurrent.futures import Future

from gameconsole.games.chess.ai.engine import ChessEngine, EngineDecision
from gameconsole.games.chess.board import Board
from gameconsole.games.chess.moves import Move


class ImmediateExecutor:
    """Ejecuta las tareas en el mismo hilo para que las pruebas sean deterministas."""

    def submit(self, fn, *args, **kwargs):
        future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class ScriptedEngine(ChessEngine):
    """Juega una lista fija de movimientos y luego el primer movimiento legal."""

    name = "motor de prueba"

    def __init__(self, moves: list[str] | None = None) -> None:
        self._moves = list(moves or [])
        self.calls = 0

    def choose_move(self, board: Board, depth: int) -> EngineDecision:
        self.calls += 1
        move = Move.from_uci(self._moves.pop(0)) if self._moves else sorted(board.legal_moves(), key=str)[0]
        return EngineDecision(move, score=12, depth=depth, nodes=345, elapsed_ms=7)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
