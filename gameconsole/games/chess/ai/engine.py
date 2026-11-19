"""Integración con el motor Prolog mediante janus-swi.

Python envía la posición en FEN y Prolog responde con el movimiento elegido,
su evaluación y la cantidad de nodos explorados. Janus asocia cada hilo de
Python a un hilo de Prolog propio, por lo que varias partidas pueden pedir
decisiones al mismo tiempo sin compartir estado de búsqueda.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..board import Board
from ..moves import Move

PROLOG_SOURCE = Path(__file__).with_name("chess_ai.pl")


class EngineError(RuntimeError):
    """El motor no pudo producir una decisión válida."""


@dataclass(frozen=True, slots=True)
class EngineDecision:
    move: Move
    score: int          # centipeones desde el punto de vista del bando que mueve
    depth: int
    nodes: int
    elapsed_ms: int


class ChessEngine(ABC):
    """Contrato de cualquier motor que decida jugadas para la computadora."""

    name: str = "engine"

    @abstractmethod
    def choose_move(self, board: Board, depth: int) -> EngineDecision:
        ...


class PrologChessEngine(ChessEngine):
    name = "SWI-Prolog · negamax alfa-beta"

    _load_lock = threading.Lock()
    _loaded = False

    def __init__(self, source: Path = PROLOG_SOURCE) -> None:
        self._source = source

    def _ensure_loaded(self):
        try:
            import janus_swi as janus
        except ImportError as error:  # pragma: no cover - depende del entorno
            raise EngineError("janus-swi no está instalado; se requiere SWI-Prolog") from error
        with PrologChessEngine._load_lock:
            if not PrologChessEngine._loaded:
                janus.consult(str(self._source))
                PrologChessEngine._loaded = True
        return janus

    def warm_up(self) -> None:
        self._ensure_loaded()

    def choose_move(self, board: Board, depth: int) -> EngineDecision:
        janus = self._ensure_loaded()
        started = time.perf_counter()
        try:
            answer = janus.query_once(
                "chess_ai:best_move(Fen, Depth, Move, Score, Nodes)",
                {"Fen": board.fen(), "Depth": depth},
            )
        except Exception as error:  # errores de Prolog llegan como excepciones de janus
            raise EngineError(f"Error en el motor Prolog: {error}") from error
        if not answer.get("truth"):
            raise EngineError("El motor Prolog no encontró movimientos")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        move = Move.from_uci(str(answer["Move"]))
        if not board.is_legal(move):
            raise EngineError(f"El motor Prolog propuso un movimiento ilegal: {move.uci}")
        return EngineDecision(move, int(answer["Score"]), depth, int(answer["Nodes"]), elapsed_ms)

    def legal_moves(self, board: Board) -> list[str]:
        """Expuesto para pruebas cruzadas con el generador de Python."""
        janus = self._ensure_loaded()
        return list(janus.query_once("chess_ai:legal_move_list(Fen, Moves)", {"Fen": board.fen()})["Moves"])
