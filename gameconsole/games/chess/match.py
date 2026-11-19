"""Partida de ajedrez jugador contra computadora (Prolog)."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Callable

from ...events.contracts import ChessEvents
from ..base import GameSession
from .ai.engine import EngineDecision, EngineError
from .board import Board, IllegalMoveError
from .clock import ChessClock, TimeControl
from .moves import Move
from .notation import to_san
from .pieces import Color
from .players import ComputerPlayer, HumanPlayer, Player
from .squares import square_name

log = logging.getLogger(__name__)


class MatchError(RuntimeError):
    """Acción inválida sobre la partida (no es tu turno, ya terminó, etc.)."""


@dataclass(frozen=True, slots=True)
class MoveRecord:
    number: int
    color: Color
    san: str
    uci: str
    piece: str
    captured: str | None
    decision_ms: int
    by_computer: bool

    def to_dict(self) -> dict:
        return {
            "number": self.number, "color": self.color.value, "san": self.san, "uci": self.uci,
            "piece": self.piece, "captured": self.captured, "decisionMs": self.decision_ms,
            "byComputer": self.by_computer,
        }


@dataclass(frozen=True, slots=True)
class GameResult:
    winner: Player | None
    reason: str          # valor del contrato: CHECKMATE | RESIGNATION | DRAW | TIMEOUT
    detail: str          # explicación para la interfaz

    def to_dict(self) -> dict:
        return {
            "winnerPlayerId": self.winner.player_id if self.winner else None,
            "winnerName": self.winner.display_name if self.winner else None,
            "winnerColor": self.winner.color.value if self.winner else None,
            "reason": self.reason,
            "detail": self.detail,
        }


class ChessMatch(GameSession):
    slug = "ajedrez"
    game_version = "1.0"
    MAX_AI_ATTEMPTS = 3

    def __init__(self, match_id: str, human: HumanPlayer, computer: ComputerPlayer,
                 control: TimeControl, events: ChessEvents, executor: Executor,
                 clock_source: Callable[[], float] = time.monotonic) -> None:
        super().__init__(match_id, events)
        if human.color is computer.color:
            raise ValueError("Los jugadores deben tener colores distintos")
        self._chess_events = events
        self._human = human
        self._computer = computer
        self._players = {human.color: human, computer.color: computer}
        self._board = Board.initial()
        self._clock = ChessClock(control, clock_source)
        self._executor = executor
        self._history: list[MoveRecord] = []
        self._positions: Counter[str] = Counter({self._board.position_key(): 1})
        self._captured: dict[Color, list[str]] = {Color.WHITE: [], Color.BLACK: []}
        self._result: GameResult | None = None
        self._last_move: Move | None = None
        self._last_decision: EngineDecision | None = None
        self._ai_thinking = False
        self._ai_error: str | None = None
        self._ai_attempts = 0
        self._lock = threading.RLock()
        self._started = False

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            white, black = self._players[Color.WHITE], self._players[Color.BLACK]
            control = self._clock.control
            self._chess_events.match_started(
                [(white.player_id, Color.WHITE.value), (black.player_id, Color.BLACK.value)],
                control.initial_ms, control.increment_ms,
            )
            self._clock.start(Color.WHITE)
            self._maybe_schedule_computer()

    @property
    def is_finished(self) -> bool:
        return self._result is not None

    @property
    def human(self) -> HumanPlayer:
        return self._human

    @property
    def computer(self) -> ComputerPlayer:
        return self._computer

    @property
    def result(self) -> GameResult | None:
        return self._result

    @property
    def board(self) -> Board:
        return self._board

    def tick(self) -> None:
        with self._lock:
            self._check_flag()

    # ------------------------------------------------------------------ acciones
    def play_human_move(self, uci: str) -> MoveRecord:
        with self._lock:
            self._require_active()
            if self._check_flag():
                raise MatchError("Se agotó el tiempo")
            if self._board.turn is not self._human.color:
                raise MatchError("No es tu turno")
            try:
                move = Move.from_uci(uci)
            except ValueError as error:
                raise MatchError(str(error)) from error
            if not self._board.is_legal(move):
                raise MatchError(f"Movimiento ilegal: {uci}")
            return self._commit(move, decision=None)

    def resign(self) -> None:
        with self._lock:
            self._require_active()
            self._finish(GameResult(self._computer, "RESIGNATION", f"{self._human.display_name} abandonó la partida"))

    # ------------------------------------------------------------------ computadora
    def _maybe_schedule_computer(self) -> None:
        if self._result is None and self._board.turn is self._computer.color and not self._ai_thinking:
            self._ai_thinking = True
            self._executor.submit(self._run_computer_turn, len(self._history))

    def _run_computer_turn(self, ply: int) -> None:
        with self._lock:
            if self._result is not None or len(self._history) != ply:
                self._ai_thinking = False
                return
            position = self._board.copy()
        try:
            decision = self._computer.decide(position)  # Prolog trabaja fuera del candado
        except EngineError as error:
            log.exception("Fallo del motor en %s", self.match_id)
            with self._lock:
                self._ai_thinking = False
                self._ai_attempts += 1
                self._ai_error = str(error)
                if self._ai_attempts < self.MAX_AI_ATTEMPTS:
                    self._maybe_schedule_computer()
            return
        with self._lock:
            self._ai_thinking = False
            if self._result is not None or len(self._history) != ply:
                return
            if self._check_flag():
                return
            self._ai_error = None
            self._ai_attempts = 0
            self._last_decision = decision
            self._commit(decision.move, decision)

    # ------------------------------------------------------------------ núcleo
    def _commit(self, move: Move, decision: EngineDecision | None) -> MoveRecord:
        mover = self._players[self._board.turn]
        opponent = self._players[mover.color.opponent]
        try:
            reading = self._clock.complete_turn()
        except TimeoutError:
            self._finish(GameResult(opponent, "TIMEOUT", f"{mover.display_name} agotó su tiempo"))
            raise MatchError("Se agotó el tiempo") from None

        san = to_san(self._board, move)
        outcome = self._board.play(move)
        number = len(self._history) + 1
        origin, target = square_name(move.origin), square_name(move.target)

        if decision is not None:
            self._chess_events.ai_decision(
                mover.player_id, number, origin, target, decision.depth, decision.nodes,
                decision.score, decision.elapsed_ms,
            )
        move_event = self._chess_events.move_played(
            mover.player_id, number, outcome.piece.kind, origin, target,
            reading.decision_ms, reading.before_ms, reading.after_ms,
        )
        if outcome.captured is not None:
            self._chess_events.piece_captured(
                mover.player_id, move_event["eventId"], outcome.captured.kind, opponent.player_id,
            )
            self._captured[mover.color].append(outcome.captured.glyph)

        record = MoveRecord(number, mover.color, san, move.uci, outcome.piece.kind,
                            outcome.captured.kind if outcome.captured else None,
                            reading.decision_ms, decision is not None)
        self._history.append(record)
        self._last_move = move
        self._positions[self._board.position_key()] += 1

        result = self._detect_end(mover)
        if result is not None:
            self._finish(result)
        else:
            self._clock.start(self._board.turn)
            self._maybe_schedule_computer()
        return record

    def _detect_end(self, mover: Player) -> GameResult | None:
        board = self._board
        if not board.legal_moves():
            if board.in_check():
                return GameResult(mover, "CHECKMATE", f"Jaque mate de {mover.display_name}")
            return GameResult(None, "DRAW", "Tablas por ahogado")
        if board.has_insufficient_material():
            return GameResult(None, "DRAW", "Tablas por material insuficiente")
        if board.halfmove_clock >= 100:
            return GameResult(None, "DRAW", "Tablas por la regla de los 50 movimientos")
        if self._positions[board.position_key()] >= 3:
            return GameResult(None, "DRAW", "Tablas por triple repetición")
        return None

    def _check_flag(self) -> bool:
        if self._result is not None:
            return False
        flagged = self._clock.flagged()
        if flagged is None:
            return False
        loser = self._players[flagged]
        self._finish(GameResult(self._players[flagged.opponent], "TIMEOUT", f"{loser.display_name} agotó su tiempo"))
        return True

    def _finish(self, result: GameResult) -> None:
        if self._result is not None:
            return
        self._clock.stop()
        self._result = result
        self._chess_events.match_finished(result.winner.player_id if result.winner else None, result.reason)

    def _require_active(self) -> None:
        if not self._started:
            raise MatchError("La partida no ha iniciado")
        if self._result is not None:
            raise MatchError("La partida ya terminó")

    # ------------------------------------------------------------------ vistas
    def status_line(self) -> str:
        if self._result is not None:
            return self._result.detail
        if self._ai_thinking:
            return "La IA está pensando"
        return "Tu turno" if self._board.turn is self._human.color else "Turno de la IA"

    def snapshot(self) -> dict:
        with self._lock:
            self._check_flag()
            board = self._board
            human_turn = self._result is None and board.turn is self._human.color
            check_square = None
            if self._result is None or self._result.reason == "CHECKMATE":
                if board.in_check():
                    check_square = square_name(board.king_square(board.turn))
            decision = self._last_decision
            return {
                "matchId": self.match_id,
                "gameId": self.game_id,
                "gameVersion": self.game_version,
                "finished": self._result is not None,
                "status": self.status_line(),
                "turn": board.turn.value,
                "fen": board.fen(),
                "board": board.grid(),
                "orientation": self._human.color.value,
                "players": [self._players[Color.WHITE].describe(), self._players[Color.BLACK].describe()],
                "clock": {
                    "control": self._clock.control.label,
                    "WHITE": self._clock.remaining_ms(Color.WHITE),
                    "BLACK": self._clock.remaining_ms(Color.BLACK),
                    "running": self._clock.running.value if self._clock.running else None,
                },
                "legalMoves": [
                    {"from": square_name(m.origin), "to": square_name(m.target), "promotion": m.promotion}
                    for m in board.legal_moves()
                ] if human_turn else [],
                "lastMove": None if self._last_move is None else {
                    "from": square_name(self._last_move.origin), "to": square_name(self._last_move.target),
                },
                "check": check_square,
                "history": [record.to_dict() for record in self._history],
                "captured": {color.value: list(glyphs) for color, glyphs in self._captured.items()},
                "result": self._result.to_dict() if self._result else None,
                "ai": {
                    "engine": self._computer.engine_name,
                    "depth": self._computer.depth,
                    "thinking": self._ai_thinking,
                    "error": self._ai_error,
                    "lastDecision": None if decision is None else {
                        "move": decision.move.uci, "score": decision.score, "depth": decision.depth,
                        "nodes": decision.nodes, "thinkMs": decision.elapsed_ms,
                    },
                },
                "events": {"emitted": self.events_emitted, "recent": self.recent_events()},
            }
