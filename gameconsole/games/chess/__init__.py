"""Ajedrez: modelo orientado a objetos y partida contra la IA en Prolog."""

from .board import Board, IllegalMoveError
from .clock import ChessClock, TimeControl
from .match import ChessMatch, MatchError
from .moves import Move
from .pieces import Color
from .players import ComputerPlayer, HumanPlayer, Player

__all__ = [
    "Board", "IllegalMoveError", "ChessClock", "TimeControl", "ChessMatch", "MatchError",
    "Move", "Color", "ComputerPlayer", "HumanPlayer", "Player",
]
