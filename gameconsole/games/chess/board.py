"""Tablero y reglas de legalidad del ajedrez."""

from __future__ import annotations

from typing import Iterator

from .moves import Move, MoveOutcome
from .pieces import (
    DIAGONAL,
    ORTHOGONAL,
    PIECE_TYPES,
    Bishop,
    Color,
    King,
    Knight,
    Pawn,
    Piece,
    Queen,
    Rook,
    piece_from_fen,
)
from .squares import offset, parse_square, square_name

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class IllegalMoveError(ValueError):
    """El movimiento no es legal en la posición actual."""


class CastlingRights:
    """Derechos de enroque como valor inmutable (K, Q, k, q)."""

    __slots__ = ("_flags",)

    # casilla de la torre -> derecho que se pierde si la torre se mueve o es capturada
    ROOK_SQUARES = {7: "K", 0: "Q", 63: "k", 56: "q"}

    def __init__(self, flags: str = "KQkq") -> None:
        self._flags = frozenset(flag for flag in flags if flag in "KQkq")

    def allows(self, color: Color, kingside: bool) -> bool:
        flag = "K" if kingside else "Q"
        return (flag if color is Color.WHITE else flag.lower()) in self._flags

    def without(self, *flags: str) -> "CastlingRights":
        return CastlingRights("".join(self._flags.difference(flags)))

    @property
    def fen(self) -> str:
        text = "".join(flag for flag in "KQkq" if flag in self._flags)
        return text or "-"


class Board:
    """Posición completa: piezas, turno, enroques, captura al paso y contadores."""

    def __init__(self) -> None:
        self._squares: list[Piece | None] = [None] * 64
        self.turn = Color.WHITE
        self.castling = CastlingRights("")
        self.en_passant: int | None = None
        self.halfmove_clock = 0
        self.fullmove_number = 1

    # ------------------------------------------------------------------ creación
    @classmethod
    def initial(cls) -> "Board":
        return cls.from_fen(START_FEN)

    @classmethod
    def from_fen(cls, fen: str) -> "Board":
        fields = fen.split()
        if len(fields) < 4:
            raise ValueError("FEN incompleto")
        board = cls()
        rows = fields[0].split("/")
        if len(rows) != 8:
            raise ValueError("FEN debe tener 8 filas")
        for row_index, row in enumerate(rows):
            rank = 7 - row_index
            file = 0
            for symbol in row:
                if symbol.isdigit():
                    file += int(symbol)
                else:
                    if file > 7:
                        raise ValueError("Fila FEN demasiado larga")
                    board._squares[rank * 8 + file] = piece_from_fen(symbol)
                    file += 1
            if file != 8:
                raise ValueError("Fila FEN con longitud incorrecta")
        board.turn = Color.from_fen(fields[1])
        board.castling = CastlingRights(fields[2])
        board.en_passant = None if fields[3] == "-" else parse_square(fields[3])
        board.halfmove_clock = int(fields[4]) if len(fields) > 4 else 0
        board.fullmove_number = int(fields[5]) if len(fields) > 5 else 1
        return board

    def copy(self) -> "Board":
        clone = Board()
        clone._squares = self._squares.copy()  # las piezas son inmutables
        clone.turn = self.turn
        clone.castling = self.castling
        clone.en_passant = self.en_passant
        clone.halfmove_clock = self.halfmove_clock
        clone.fullmove_number = self.fullmove_number
        return clone

    # ------------------------------------------------------------------ consultas
    def piece_at(self, square: int) -> Piece | None:
        return self._squares[square]

    def pieces(self, color: Color | None = None) -> Iterator[tuple[int, Piece]]:
        for square, piece in enumerate(self._squares):
            if piece is not None and (color is None or piece.color is color):
                yield square, piece

    def king_square(self, color: Color) -> int:
        for square, piece in self.pieces(color):
            if isinstance(piece, King):
                return square
        raise ValueError(f"No hay rey {color.name}")

    def is_attacked(self, square: int, by: Color) -> bool:
        """Indica si ``square`` está atacada por alguna pieza de ``by``."""
        for file_step, rank_step in Knight.offsets:
            target = offset(square, file_step, rank_step)
            if target is not None and self._squares[target] == Knight(by):
                return True
        for file_step, rank_step in King.offsets:
            target = offset(square, file_step, rank_step)
            if target is not None and self._squares[target] == King(by):
                return True
        for file_step in (-1, 1):
            # un peón de ``by`` ataca hacia su avance: se busca detrás de la casilla
            target = offset(square, file_step, -by.forward)
            if target is not None and self._squares[target] == Pawn(by):
                return True
        for directions, attackers in ((ORTHOGONAL, (Rook, Queen)), (DIAGONAL, (Bishop, Queen))):
            for file_step, rank_step in directions:
                target = offset(square, file_step, rank_step)
                while target is not None:
                    piece = self._squares[target]
                    if piece is not None:
                        if piece.color is by and isinstance(piece, attackers):
                            return True
                        break
                    target = offset(target, file_step, rank_step)
        return False

    def in_check(self, color: Color | None = None) -> bool:
        color = color or self.turn
        return self.is_attacked(self.king_square(color), color.opponent)

    # ------------------------------------------------------------------ generación
    def castling_moves(self, color: Color) -> Iterator[Move]:
        """Enroques posibles: casillas libres y rey que no pasa por jaque."""
        home = 4 if color is Color.WHITE else 60
        if self._squares[home] != King(color):
            return
        enemy = color.opponent
        if self.castling.allows(color, kingside=True):
            if (self._squares[home + 3] == Rook(color)
                    and self._squares[home + 1] is None and self._squares[home + 2] is None
                    and not any(self.is_attacked(sq, enemy) for sq in (home, home + 1, home + 2))):
                yield Move(home, home + 2)
        if self.castling.allows(color, kingside=False):
            if (self._squares[home - 4] == Rook(color)
                    and all(self._squares[sq] is None for sq in (home - 1, home - 2, home - 3))
                    and not any(self.is_attacked(sq, enemy) for sq in (home, home - 1, home - 2))):
                yield Move(home, home - 2)

    def pseudo_legal_moves(self) -> Iterator[Move]:
        for square, piece in self.pieces(self.turn):
            yield from piece.pseudo_legal_moves(self, square)

    def legal_moves(self) -> list[Move]:
        moves = []
        for move in self.pseudo_legal_moves():
            trial = self.copy()
            trial._apply(move)
            if not trial.is_attacked(trial.king_square(self.turn), self.turn.opponent):
                moves.append(move)
        return moves

    def is_legal(self, move: Move) -> bool:
        return move in self.legal_moves()

    # ------------------------------------------------------------------ ejecución
    def play(self, move: Move) -> MoveOutcome:
        """Aplica un movimiento legal y devuelve lo sucedido."""
        if not self.is_legal(move):
            raise IllegalMoveError(f"Movimiento ilegal: {move.uci}")
        return self._apply(move)

    def _apply(self, move: Move) -> MoveOutcome:
        piece = self._squares[move.origin]
        if piece is None:
            raise IllegalMoveError(f"No hay pieza en {square_name(move.origin)}")
        color = piece.color
        captured = self._squares[move.target]
        is_en_passant = isinstance(piece, Pawn) and move.target == self.en_passant and captured is None \
            and move.origin % 8 != move.target % 8
        is_castling = isinstance(piece, King) and abs(move.target - move.origin) == 2

        if is_en_passant:
            captured_square = move.target - 8 * color.forward
            captured = self._squares[captured_square]
            self._squares[captured_square] = None

        promoted_to = PIECE_TYPES[move.promotion](color) if move.promotion else None
        self._squares[move.target] = promoted_to or piece
        self._squares[move.origin] = None

        if is_castling:
            if move.target > move.origin:  # lado del rey
                rook_from, rook_to = move.origin + 3, move.origin + 1
            else:
                rook_from, rook_to = move.origin - 4, move.origin - 1
            self._squares[rook_to] = self._squares[rook_from]
            self._squares[rook_from] = None

        lost = []
        if isinstance(piece, King):
            lost += ["K", "Q"] if color is Color.WHITE else ["k", "q"]
        for square in (move.origin, move.target):
            if square in CastlingRights.ROOK_SQUARES:
                lost.append(CastlingRights.ROOK_SQUARES[square])
        if lost:
            self.castling = self.castling.without(*lost)

        double_push = isinstance(piece, Pawn) and abs(move.target - move.origin) == 16
        self.en_passant = (move.origin + move.target) // 2 if double_push else None
        self.halfmove_clock = 0 if isinstance(piece, Pawn) or captured is not None else self.halfmove_clock + 1
        if color is Color.BLACK:
            self.fullmove_number += 1
        self.turn = color.opponent
        return MoveOutcome(move, piece, captured, is_castling, is_en_passant, promoted_to)

    # ------------------------------------------------------------------ estado
    def fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row, empty = "", 0
            for file in range(8):
                piece = self._squares[rank * 8 + file]
                if piece is None:
                    empty += 1
                else:
                    row += (str(empty) if empty else "") + piece.fen_symbol
                    empty = 0
            rows.append(row + (str(empty) if empty else ""))
        en_passant = square_name(self.en_passant) if self.en_passant is not None else "-"
        return (f"{'/'.join(rows)} {self.turn.fen} {self.castling.fen} {en_passant} "
                f"{self.halfmove_clock} {self.fullmove_number}")

    def position_key(self) -> str:
        """Clave para detectar repeticiones (sin contadores)."""
        return " ".join(self.fen().split()[:4])

    def has_insufficient_material(self) -> bool:
        """Rey contra rey, o rey contra rey y una pieza menor."""
        others = [piece for _, piece in self.pieces() if not isinstance(piece, King)]
        if not others:
            return True
        return len(others) == 1 and isinstance(others[0], (Knight, Bishop))

    def grid(self) -> list[dict | None]:
        """Representación serializable para la interfaz (a1..h8)."""
        return [
            None if piece is None else {"color": piece.color.value, "kind": piece.kind, "glyph": piece.glyph}
            for piece in self._squares
        ]
