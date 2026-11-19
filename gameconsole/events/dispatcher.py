"""Envío concurrente de eventos a GameStats.

Estrategia:
  * Una cola FIFO por partida (``matchId``). GameStats exige una ``sequence``
    continua, así que los eventos de una misma partida se envían en serie.
  * Un grupo de hilos compartido drena las colas: partidas distintas avanzan en
    paralelo y una partida lenta o con fallos no bloquea a las demás.
  * ``submit`` nunca hace E/S: el juego encola y continúa sin esperar la red.
  * Fallos transitorios (red caída, 5xx) se reintentan con espera exponencial;
    si persisten, la cola se pausa y se reprograma sin perder el orden.
  * 409 (``eventId`` duplicado) significa que GameStats ya lo había aceptado
    en un intento previo: se considera entregado (entrega idempotente).
  * 400/422 son rechazos de contrato: se registran y la cola de esa partida se
    detiene, porque los eventos siguientes romperían la secuencia.
  * Excepción: si GameStats se reinició, olvida las partidas en curso y responde
    que la partida debe empezar con MATCH_STARTED. En ese caso la cola se
    re-sincroniza reenviando todo el historial con los mismos ``eventId``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: dict | None = None


class TransportError(RuntimeError):
    """Fallo de comunicación (conexión rechazada, tiempo de espera, etc.)."""


class EventTransport(Protocol):
    def post_event(self, event: dict) -> TransportResponse:
        ...


class HttpEventTransport:
    """POST /api/v1/events del servicio de ingestión Go de GameStats."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._url = base_url.rstrip("/") + "/api/v1/events"
        self._timeout = timeout

    def post_event(self, event: dict) -> TransportResponse:
        request = urllib.request.Request(
            self._url,
            data=json.dumps(event).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return TransportResponse(response.status, _read_json(response.read()))
        except urllib.error.HTTPError as error:
            return TransportResponse(error.code, _read_json(error.read()))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            raise TransportError(str(error)) from error


def _read_json(raw: bytes) -> dict | None:
    try:
        value = json.loads(raw.decode("utf-8")) if raw else None
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 5            # intentos por ráfaga antes de pausar la cola
    base_delay: float = 0.25     # segundos
    max_delay: float = 4.0
    pause: float = 10.0          # espera antes de reanudar una cola pausada

    def delay(self, attempt: int) -> float:
        return min(self.max_delay, self.base_delay * (2 ** attempt))


@dataclass
class MatchChannel:
    match_id: str
    game_id: str
    queue: deque = field(default_factory=deque)
    active: bool = False
    delivered: int = 0
    duplicates: int = 0
    retries: int = 0
    state: str = "OK"            # OK | RETRYING | REJECTED
    last_error: str | None = None
    rejected_event: dict | None = None
    history: list = field(default_factory=list)   # eventos ya entregados, para re-sincronizar
    resyncs: int = 0

    def snapshot(self) -> dict:
        return {
            "matchId": self.match_id,
            "gameId": self.game_id,
            "pending": len(self.queue),
            "delivered": self.delivered,
            "duplicates": self.duplicates,
            "retries": self.retries,
            "resyncs": self.resyncs,
            "state": self.state,
            "lastError": self.last_error,
        }


class EventDispatcher:
    MAX_RESYNCS = 5

    def __init__(self, transport: EventTransport, max_workers: int = 8,
                 retry: RetryPolicy = RetryPolicy(),
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._transport = transport
        self._retry = retry
        self._sleep = sleep
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="gamestats-send")
        self._channels: dict[str, MatchChannel] = {}
        self._lock = threading.Lock()
        self._closed = False

    # ------------------------------------------------------------------ API
    def submit(self, event: dict) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("El despachador está cerrado")
            channel = self._channels.get(event["matchId"])
            if channel is None:
                channel = MatchChannel(event["matchId"], event["gameId"])
                self._channels[event["matchId"]] = channel
            channel.queue.append(event)
            if channel.active or channel.state == "REJECTED":
                return
            channel.active = True
        self._executor.submit(self._drain, channel)

    def status(self, match_id: str) -> dict | None:
        with self._lock:
            channel = self._channels.get(match_id)
            return channel.snapshot() if channel else None

    def overview(self) -> dict:
        with self._lock:
            channels = list(self._channels.values())
            return {
                "matches": len(channels),
                "pending": sum(len(c.queue) for c in channels),
                "delivered": sum(c.delivered for c in channels),
                "retrying": sum(1 for c in channels if c.state == "RETRYING"),
                "rejected": sum(1 for c in channels if c.state == "REJECTED"),
            }

    def flush(self, timeout: float = 10.0) -> bool:
        """Espera a que todas las colas se vacíen (útil en pruebas y al apagar)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                busy = any(c.queue and c.state != "REJECTED" for c in self._channels.values())
            if not busy:
                return True
            time.sleep(0.02)
        return False

    def shutdown(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ envío
    def _drain(self, channel: MatchChannel) -> None:
        while True:
            with self._lock:
                if not channel.queue:
                    channel.active = False
                    return
                event = channel.queue[0]
            outcome = self._deliver(channel, event)
            with self._lock:
                if outcome == "delivered":
                    channel.history.append(channel.queue.popleft())
                    channel.state = "OK"
                    channel.last_error = None
                    continue
                if outcome == "resync":
                    channel.queue = deque(channel.history + list(channel.queue))
                    channel.history = []
                    channel.resyncs += 1
                    channel.state = "RESYNCING"
                    log.warning("GameStats no conoce la partida %s; se reenvía su historial", channel.match_id)
                    continue
                if outcome == "rejected":
                    channel.active = False
                    return
                # outcome == "retry": se pausa y se reprograma sin perder el orden
                channel.state = "RETRYING"
            timer = threading.Timer(self._retry.pause, self._resume, args=(channel,))
            timer.daemon = True
            timer.start()
            return

    def _resume(self, channel: MatchChannel) -> None:
        with self._lock:
            if self._closed:
                return
        try:
            self._executor.submit(self._drain, channel)
        except RuntimeError:  # el ejecutor ya fue cerrado
            pass

    def _deliver(self, channel: MatchChannel, event: dict) -> str:
        for attempt in range(self._retry.attempts):
            if attempt:
                with self._lock:
                    channel.retries += 1
                self._sleep(self._retry.delay(attempt - 1))
            try:
                response = self._transport.post_event(event)
            except TransportError as error:
                self._note_error(channel, f"Sin conexión con GameStats: {error}")
                continue
            if response.status in (200, 201):
                with self._lock:
                    channel.delivered += 1
                return "delivered"
            if response.status == 409:
                with self._lock:
                    channel.delivered += 1
                    channel.duplicates += 1
                return "delivered"
            message = (response.body or {}).get("message") or f"HTTP {response.status}"
            if self._match_forgotten(channel, event, response.status, message):
                return "resync"
            if response.status in (400, 404, 413, 422):
                with self._lock:
                    channel.state = "REJECTED"
                    channel.last_error = message
                    channel.rejected_event = event
                log.error("GameStats rechazó %s (%s): %s", event["eventId"], event["type"], message)
                return "rejected"
            self._note_error(channel, message)  # 5xx: el servicio puede recuperarse
        return "retry"

    def _match_forgotten(self, channel: MatchChannel, event: dict, status: int, message: str) -> bool:
        """GameStats perdió el estado de la partida (por ejemplo, tras reiniciarse)."""
        with self._lock:
            return (status == 422 and event["type"] != "MATCH_STARTED" and "MATCH_STARTED" in message
                    and bool(channel.history) and channel.resyncs < self.MAX_RESYNCS)

    def _note_error(self, channel: MatchChannel, message: str) -> None:
        with self._lock:
            channel.last_error = message
        log.warning("Envío a GameStats pendiente para %s: %s", channel.match_id, message)
