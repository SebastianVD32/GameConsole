"""Jugadores de una partida de ajedrez."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .ai.engine import ChessEngine, EngineDecision
from .board import Board
from .pieces import Color


class Player(ABC):
    """Participante identificado ante GameStats por ``player_id``."""

    def __init__(self, player_id: str, display_name: str, color: Color) -> None:
        self._player_id = player_id
        self._display_name = display_name
        self._color = color

    @property
    def player_id(self) -> str:
        return self._player_id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def color(self) -> Color:
        return self._color

    @property
    @abstractmethod
    def is_automated(self) -> bool:
        ...

    def describe(self) -> dict:
        return {
            "playerId": self._player_id,
            "name": self._display_name,
            "color": self._color.value,
            "automated": self.is_automated,
        }


class HumanPlayer(Player):
    """Jugador que decide desde la interfaz web."""

    @property
    def is_automated(self) -> bool:
        return False


class ComputerPlayer(Player):
    """Jugador controlado por un motor; delega la decisión en él."""

    def __init__(self, player_id: str, display_name: str, color: Color,
                 engine: ChessEngine, depth: int) -> None:
        super().__init__(player_id, display_name, color)
        if depth < 1:
            raise ValueError("La profundidad debe ser positiva")
        self._engine = engine
        self._depth = depth

    @property
    def is_automated(self) -> bool:
        return True

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def engine_name(self) -> str:
        return self._engine.name

    def decide(self, board: Board) -> EngineDecision:
        return self._engine.choose_move(board, self._depth)

    def describe(self) -> dict:
        return {**super().describe(), "engine": self._engine.name, "depth": self._depth}
