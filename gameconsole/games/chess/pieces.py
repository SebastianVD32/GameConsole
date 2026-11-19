"""Piezas de ajedrez.

Cada pieza conoce únicamente su forma de moverse y de atacar. El tablero aporta
el contexto (casillas ocupadas, derechos de enroque, captura al paso) y decide la
legalidad final, por lo que las piezas no conocen las reglas de jaque.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Iterator

from .moves import Move
from .squares import offset

if TYPE_CHECKING:
    from .board import Board


class Color(Enum):
    WHITE = "WHITE"
    BLACK = "BLACK"

    @property
    def opponent(self) -> "Color":
        return Color.BLACK if self is Color.WHITE else Color.WHITE

    @property
    def forward(self) -> int:
        """Dirección de avance de los peones en filas."""
        return 1 if self is Color.WHITE else -1

    @property
    def fen(self) -> str:
        return "w" if self is Color.WHITE else "b"

    @property
    def label(self) -> str:
        return "Blancas" if self is Color.WHITE else "Negras"

    @classmethod
    def from_fen(cls, letter: str) -> "Color":
        return cls.WHITE if letter == "w" else cls.BLACK


class Piece(ABC):
    """Abstracción común a todas las piezas."""

    kind: ClassVar[str]          # Nombre del contrato de GameStats (KING, QUEEN, ...)
    letter: ClassVar[str]        # Letra FEN en minúscula
    value: ClassVar[int]         # Valor material en centipeones
    glyphs: ClassVar[tuple[str, str]]  # (blancas, negras)

    __slots__ = ("_color",)

    def __init__(self, color: Color) -> None:
        self._color = color

    @property
    def color(self) -> Color:
        return self._color

    @property
    def fen_symbol(self) -> str:
        return self.letter.upper() if self._color is Color.WHITE else self.letter

    @property
    def glyph(self) -> str:
        return self.glyphs[0] if self._color is Color.WHITE else self.glyphs[1]

    @property
    def san_letter(self) -> str:
        return self.letter.upper()

    @abstractmethod
    def attacked_squares(self, board: "Board", square: int) -> Iterator[int]:
        """Casillas que la pieza ataca desde ``square``."""

    def pseudo_legal_moves(self, board: "Board", square: int) -> Iterator[Move]:
        """Movimientos sin comprobar si dejan al propio rey en jaque."""
        for target in self.attacked_squares(board, square):
            occupant = board.piece_at(target)
            if occupant is None or occupant.color is not self._color:
                yield Move(square, target)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Piece) and type(self) is type(other) and self._color is other._color

    def __hash__(self) -> int:
        return hash((type(self), self._color))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._color.name})"


class LeaperPiece(Piece):
    """Pieza que salta a casillas fijas (caballo y rey)."""

    offsets: ClassVar[tuple[tuple[int, int], ...]]

    def attacked_squares(self, board: "Board", square: int) -> Iterator[int]:
        for file_step, rank_step in self.offsets:
            target = offset(square, file_step, rank_step)
            if target is not None:
                yield target


class SlidingPiece(Piece):
    """Pieza que se desliza hasta encontrar un obstáculo (torre, alfil, dama)."""

    directions: ClassVar[tuple[tuple[int, int], ...]]

    def attacked_squares(self, board: "Board", square: int) -> Iterator[int]:
        for file_step, rank_step in self.directions:
            target = offset(square, file_step, rank_step)
            while target is not None:
                yield target
                if board.piece_at(target) is not None:
                    break
                target = offset(target, file_step, rank_step)


ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))


class Knight(LeaperPiece):
    kind = "KNIGHT"
    letter = "n"
    value = 320
    glyphs = ("♘", "♞")
    offsets = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))


class Bishop(SlidingPiece):
    kind = "BISHOP"
    letter = "b"
    value = 330
    glyphs = ("♗", "♝")
    directions = DIAGONAL


class Rook(SlidingPiece):
    kind = "ROOK"
    letter = "r"
    value = 500
    glyphs = ("♖", "♜")
    directions = ORTHOGONAL


class Queen(SlidingPiece):
    kind = "QUEEN"
    letter = "q"
    value = 900
    glyphs = ("♕", "♛")
    directions = ORTHOGONAL + DIAGONAL


class King(LeaperPiece):
    kind = "KING"
    letter = "k"
    value = 0
    glyphs = ("♔", "♚")
    offsets = ORTHOGONAL + DIAGONAL

    def pseudo_legal_moves(self, board: "Board", square: int) -> Iterator[Move]:
        yield from super().pseudo_legal_moves(board, square)
        yield from board.castling_moves(self.color)


class Pawn(Piece):
    kind = "PAWN"
    letter = "p"
    value = 100
    glyphs = ("♙", "♟")

    PROMOTIONS: ClassVar[tuple[str, ...]] = ("q", "r", "b", "n")

    def attacked_squares(self, board: "Board", square: int) -> Iterator[int]:
        for file_step in (-1, 1):
            target = offset(square, file_step, self.color.forward)
            if target is not None:
                yield target

    def pseudo_legal_moves(self, board: "Board", square: int) -> Iterator[Move]:
        forward = self.color.forward
        start_rank = 1 if self.color is Color.WHITE else 6

        one_step = offset(square, 0, forward)
        if one_step is not None and board.piece_at(one_step) is None:
            yield from self._with_promotions(square, one_step)
            two_step = offset(square, 0, 2 * forward)
            if square // 8 == start_rank and two_step is not None and board.piece_at(two_step) is None:
                yield Move(square, two_step)

        for target in self.attacked_squares(board, square):
            occupant = board.piece_at(target)
            if occupant is not None and occupant.color is not self.color:
                yield from self._with_promotions(square, target)
            elif occupant is None and target == board.en_passant:
                yield Move(square, target)

    def _with_promotions(self, origin: int, target: int) -> Iterator[Move]:
        if target // 8 in (0, 7):
            for letter in self.PROMOTIONS:
                yield Move(origin, target, letter)
        else:
            yield Move(origin, target)


PIECE_TYPES: dict[str, type[Piece]] = {cls.letter: cls for cls in (Pawn, Knight, Bishop, Rook, Queen, King)}


def piece_from_fen(symbol: str) -> Piece:
    color = Color.WHITE if symbol.isupper() else Color.BLACK
    try:
        return PIECE_TYPES[symbol.lower()](color)
    except KeyError as error:
        raise ValueError(f"Pieza FEN desconocida: {symbol!r}") from error
