"""Representación de movimientos y de su resultado."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .squares import parse_square, square_name

if TYPE_CHECKING:
    from .pieces import Piece


@dataclass(frozen=True, slots=True)
class Move:
    """Movimiento expresado como origen, destino y promoción opcional."""

    origin: int
    target: int
    promotion: str | None = None

    @property
    def uci(self) -> str:
        return f"{square_name(self.origin)}{square_name(self.target)}{self.promotion or ''}"

    @classmethod
    def from_uci(cls, text: str) -> "Move":
        text = text.strip().lower()
        if len(text) not in (4, 5):
            raise ValueError(f"Movimiento inválido: {text!r}")
        promotion = text[4] if len(text) == 5 else None
        if promotion is not None and promotion not in "qrbn":
            raise ValueError(f"Promoción inválida: {promotion!r}")
        return cls(parse_square(text[:2]), parse_square(text[2:4]), promotion)

    def __str__(self) -> str:
        return self.uci


@dataclass(frozen=True, slots=True)
class MoveOutcome:
    """Lo que ocurrió en el tablero al aplicar un movimiento legal."""

    move: Move
    piece: "Piece"
    captured: "Piece | None"
    is_castling: bool
    is_en_passant: bool
    promoted_to: "Piece | None"
