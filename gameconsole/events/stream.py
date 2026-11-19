"""Construcción de eventos con el sobre común de GameStats.

Cada partida tiene su propio ``EventStream``: genera ``eventId`` únicos, una
``sequence`` continua que empieza en 1 y marcas de tiempo UTC que nunca
retroceden. Así los eventos de partidas concurrentes no se mezclan.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Protocol


class EventSink(Protocol):
    """Destino de eventos (normalmente el despachador hacia GameStats)."""

    def submit(self, event: dict) -> None:
        ...


class MemorySink:
    """Destino en memoria, útil para pruebas o cuando GameStats no está configurado."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def submit(self, event: dict) -> None:
        self.events.append(event)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventStream:
    def __init__(self, game_id: str, game_version: str, match_id: str, sink: EventSink,
                 now: Callable[[], datetime] = utc_now,
                 id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
                 history: int = 50) -> None:
        self._game_id = game_id
        self._game_version = game_version
        self._match_id = match_id
        self._sink = sink
        self._now = now
        self._id_factory = id_factory
        self._sequence = 0
        self._last_time: datetime | None = None
        self._recent: deque[dict] = deque(maxlen=history)
        self._lock = threading.Lock()

    @property
    def match_id(self) -> str:
        return self._match_id

    @property
    def game_id(self) -> str:
        return self._game_id

    @property
    def count(self) -> int:
        return self._sequence

    def emit(self, event_type: str, player_id: str | None, data: dict) -> dict:
        with self._lock:
            moment = self._now()
            if self._last_time is not None and moment < self._last_time:
                moment = self._last_time
            self._last_time = moment
            self._sequence += 1
            event = {
                "eventId": self._id_factory(),
                "timestamp": format_timestamp(moment),
                "gameId": self._game_id,
                "gameVersion": self._game_version,
                "matchId": self._match_id,
                "sequence": self._sequence,
                "playerId": player_id,
                "type": event_type,
                "data": data,
            }
            self._recent.appendleft(event)
            # Se entrega dentro del candado para que el despachador reciba los
            # eventos de esta partida exactamente en el orden de su secuencia.
            self._sink.submit(event)
        return event

    def recent(self, limit: int = 15) -> list[dict]:
        with self._lock:
            return list(self._recent)[:limit]
