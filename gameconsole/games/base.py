"""Abstracción común de una partida (instancia de juego) en la consola."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import ClassVar

from ..events.contracts import GameEvents


class GameSession(ABC):
    """Una instancia en ejecución de un juego.

    Cada sesión tiene un ``match_id`` único y su propio flujo de eventos, de modo
    que varias sesiones pueden convivir (en una pestaña o en varias) sin mezclar
    sus eventos.
    """

    slug: ClassVar[str]          # identificador de la consola (p. ej. "ajedrez")
    game_version: ClassVar[str]

    def __init__(self, match_id: str, events: GameEvents) -> None:
        self._match_id = match_id
        self._events = events
        self._created_at = datetime.now(timezone.utc)

    @property
    def match_id(self) -> str:
        return self._match_id

    @property
    def game_id(self) -> str:
        return self._events.game_id

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def events_emitted(self) -> int:
        return self._events.stream.count

    def recent_events(self, limit: int = 12) -> list[dict]:
        return [
            {"eventId": e["eventId"], "sequence": e["sequence"], "type": e["type"],
             "timestamp": e["timestamp"], "playerId": e["playerId"]}
            for e in self._events.stream.recent(limit)
        ]

    @abstractmethod
    def start(self) -> None:
        """Emite MATCH_STARTED y deja la partida lista para jugar."""

    @property
    @abstractmethod
    def is_finished(self) -> bool:
        ...

    @abstractmethod
    def snapshot(self) -> dict:
        """Estado serializable para la interfaz."""

    @abstractmethod
    def status_line(self) -> str:
        """Descripción breve para listados de partidas."""

    def tick(self) -> None:
        """Mantenimiento periódico (p. ej. tiempo agotado). Por defecto no hace nada."""

    def summary(self) -> dict:
        return {
            "matchId": self._match_id,
            "slug": self.slug,
            "gameId": self.game_id,
            "finished": self.is_finished,
            "status": self.status_line(),
            "createdAt": self._created_at.isoformat(),
        }
