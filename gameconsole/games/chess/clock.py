"""Reloj de ajedrez con incremento (Fischer).

Los valores que produce cumplen exactamente la regla que valida GameStats:
``clockAfterMs = clockBeforeMs - decisionTimeMs + incrementMs``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .pieces import Color


@dataclass(frozen=True, slots=True)
class TimeControl:
    initial_ms: int
    increment_ms: int

    def __post_init__(self) -> None:
        if self.initial_ms <= 0 or self.increment_ms < 0:
            raise ValueError("Control de tiempo inválido")

    @property
    def label(self) -> str:
        return f"{self.initial_ms // 60000}+{self.increment_ms // 1000}"


@dataclass(frozen=True, slots=True)
class ClockReading:
    decision_ms: int
    before_ms: int
    after_ms: int


class ChessClock:
    def __init__(self, control: TimeControl, now: Callable[[], float] = time.monotonic) -> None:
        self._control = control
        self._now = now
        self._remaining = {Color.WHITE: control.initial_ms, Color.BLACK: control.initial_ms}
        self._running: Color | None = None
        self._started_at = 0.0

    @property
    def control(self) -> TimeControl:
        return self._control

    @property
    def running(self) -> Color | None:
        return self._running

    def start(self, color: Color) -> None:
        self._running = color
        self._started_at = self._now()

    def elapsed_ms(self) -> int:
        if self._running is None:
            return 0
        return int((self._now() - self._started_at) * 1000)

    def remaining_ms(self, color: Color) -> int:
        """Tiempo restante en vivo (nunca negativo)."""
        remaining = self._remaining[color]
        if color is self._running:
            remaining -= self.elapsed_ms()
        return max(0, remaining)

    def stored_ms(self, color: Color) -> int:
        """Tiempo registrado al inicio del turno, tal como lo conoce GameStats."""
        return self._remaining[color]

    def flagged(self) -> Color | None:
        """Color cuyo tiempo se agotó, si lo hay."""
        if self._running is not None and self.elapsed_ms() >= self._remaining[self._running]:
            return self._running
        return None

    def complete_turn(self) -> ClockReading:
        """Detiene el reloj del jugador en turno, aplica el incremento y devuelve la lectura."""
        if self._running is None:
            raise RuntimeError("El reloj no está corriendo")
        color = self._running
        before = self._remaining[color]
        decision = self.elapsed_ms()
        if decision >= before:
            raise TimeoutError(f"{color.name} agotó su tiempo")
        after = before - decision + self._control.increment_ms
        self._remaining[color] = after
        self._running = None
        return ClockReading(decision, before, after)

    def stop(self) -> None:
        """Detiene el reloj sin registrar un movimiento (fin de partida)."""
        if self._running is not None:
            self._remaining[self._running] = self.remaining_ms(self._running)
        self._running = None
