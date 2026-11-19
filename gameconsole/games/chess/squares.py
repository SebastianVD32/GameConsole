"""Utilidades de casillas: índice 0..63 = fila * 8 + columna (a1 = 0, h8 = 63)."""

from __future__ import annotations

FILES = "abcdefgh"


def square_name(index: int) -> str:
    return f"{FILES[index % 8]}{index // 8 + 1}"


def parse_square(name: str) -> int:
    if len(name) != 2 or name[0] not in FILES or name[1] not in "12345678":
        raise ValueError(f"Casilla inválida: {name!r}")
    return (int(name[1]) - 1) * 8 + FILES.index(name[0])


def offset(index: int, file_step: int, rank_step: int) -> int | None:
    file = index % 8 + file_step
    rank = index // 8 + rank_step
    if 0 <= file < 8 and 0 <= rank < 8:
        return rank * 8 + file
    return None
