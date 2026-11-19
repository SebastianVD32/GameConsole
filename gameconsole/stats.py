"""Consulta de resultados a GameStats.

La consola no calcula métricas: solo pide a GameStats
  * al servicio Go (ingestión): instancias iniciadas/activas/finalizadas y
    progreso de las partidas en curso (``GET /api/v1/summary``);
  * al servicio Scala (análisis): estadísticas generales y por juego
    (``GET /api/v1/stats``) y el resultado de cada partida finalizada.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone


class UpstreamError(RuntimeError):
    pass


class GameStatsQuery:
    def __init__(self, ingest_url: str, analytics_url: str, timeout: float = 3.0) -> None:
        self._ingest = ingest_url.rstrip("/")
        self._analytics = analytics_url.rstrip("/")
        self._timeout = timeout
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gamestats-query")

    @property
    def configured(self) -> bool:
        return bool(self._ingest and self._analytics)

    def _get(self, base: str, path: str) -> dict | list | None:
        if not base:
            raise UpstreamError("GameStats no está configurado")
        try:
            with urllib.request.urlopen(base + path, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise UpstreamError(f"HTTP {error.code} en {path}") from error
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise UpstreamError(f"No se pudo consultar {path}: {error}") from error

    def overview(self) -> dict:
        """Resumen de ingestión y estadísticas, consultados en paralelo."""
        ingestion = self._pool.submit(self._get, self._ingest, "/api/v1/summary")
        analytics = self._pool.submit(self._get, self._analytics, "/api/v1/stats")
        payload: dict = {"fetchedAt": datetime.now(timezone.utc).isoformat(), "errors": []}
        for key, future, label in (("ingestion", ingestion, "Ingestión (Go)"),
                                   ("analytics", analytics, "Análisis (Scala)")):
            try:
                payload[key] = future.result()
            except UpstreamError as error:
                payload[key] = None
                payload["errors"].append(f"{label}: {error}")
        return payload

    def match_result(self, match_id: str) -> dict | None:
        return self._get(self._analytics, "/api/v1/matches/" + urllib.parse.quote(match_id, safe=""))

    def health(self) -> dict:
        status = {}
        for name, base in (("ingestion", self._ingest), ("analytics", self._analytics)):
            try:
                self._get(base, "/healthz")
                status[name] = "ok"
            except UpstreamError as error:
                status[name] = str(error)
        return status
