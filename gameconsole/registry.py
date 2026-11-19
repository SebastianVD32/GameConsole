"""Registro en memoria de las partidas en ejecución."""

from __future__ import annotations

import logging
import threading

from .games.base import GameSession

log = logging.getLogger(__name__)


class MatchRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, GameSession] = {}
        self._lock = threading.Lock()
        self._ticker: threading.Thread | None = None
        self._stop = threading.Event()

    def add(self, session: GameSession) -> None:
        with self._lock:
            if session.match_id in self._sessions:
                raise ValueError(f"La partida {session.match_id} ya existe")
            self._sessions[session.match_id] = session

    def get(self, match_id: str) -> GameSession | None:
        with self._lock:
            return self._sessions.get(match_id)

    def sessions(self, slug: str | None = None) -> list[GameSession]:
        with self._lock:
            items = list(self._sessions.values())
        items = [s for s in items if slug is None or s.slug == slug]
        return sorted(items, key=lambda s: s.created_at, reverse=True)

    def tick_all(self) -> None:
        for session in self.sessions():
            if not session.is_finished:
                try:
                    session.tick()
                except Exception:  # una partida defectuosa no debe detener a las demás
                    log.exception("Error al actualizar la partida %s", session.match_id)

    def start_ticker(self, interval: float = 1.0) -> None:
        """Hilo que detecta tiempos agotados aunque nadie esté mirando la partida."""
        if self._ticker is not None:
            return

        def loop() -> None:
            while not self._stop.wait(interval):
                self.tick_all()

        self._ticker = threading.Thread(target=loop, name="match-ticker", daemon=True)
        self._ticker.start()

    def stop(self) -> None:
        self._stop.set()
