"""Notación algebraica estándar (SAN) para el historial de la partida."""

from __future__ import annotations

from .board import Board
from .moves import Move
from .pieces import King, Pawn
from .squares import FILES, square_name


def to_san(board: Board, move: Move) -> str:
    """Calcula la SAN de ``move`` en la posición ``board`` (antes de jugarlo)."""
    piece = board.piece_at(move.origin)
    if piece is None:
        raise ValueError("No hay pieza en el origen")

    if isinstance(piece, King) and abs(move.target - move.origin) == 2:
        text = "O-O" if move.target > move.origin else "O-O-O"
    else:
        is_capture = board.piece_at(move.target) is not None or (
            isinstance(piece, Pawn) and move.origin % 8 != move.target % 8
        )
        if isinstance(piece, Pawn):
            text = (FILES[move.origin % 8] + "x" if is_capture else "") + square_name(move.target)
            if move.promotion:
                text += "=" + move.promotion.upper()
        else:
            text = piece.san_letter + _disambiguation(board, move) + ("x" if is_capture else "") \
                + square_name(move.target)

    after = board.copy()
    after.play(move)
    if after.in_check():
        text += "#" if not after.legal_moves() else "+"
    return text


def _disambiguation(board: Board, move: Move) -> str:
    piece = board.piece_at(move.origin)
    rivals = [
        other.origin for other in board.legal_moves()
        if other.target == move.target and other.origin != move.origin
        and board.piece_at(other.origin) == piece
    ]
    if not rivals:
        return ""
    same_file = any(origin % 8 == move.origin % 8 for origin in rivals)
    same_rank = any(origin // 8 == move.origin // 8 for origin in rivals)
    if not same_file:
        return FILES[move.origin % 8]
    if not same_rank:
        return str(move.origin // 8 + 1)
    return square_name(move.origin)
