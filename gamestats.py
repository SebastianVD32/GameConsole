"""Same-origin bridge. GameStats retains validation and all statistical calculations."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import Blueprint, jsonify, request

stats = Blueprint("gamestats", __name__)


def forward(base, path, payload=None):
    if base == "GAMESTATS_INGESTION_URL":
        # The shared console uses INGEST_URL; retain the earlier arcade alias.
        base_url = os.environ.get("GAMESTATS_INGEST_URL", os.environ.get(base, "http://127.0.0.1:8080"))
    else:
        base_url = os.environ.get(base, "http://127.0.0.1:8081")
    url = base_url.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    upstream = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(upstream, timeout=4) as response:
            return jsonify(json.load(response)), response.status
    except HTTPError as error:
        try:
            return jsonify(json.load(error)), error.code
        except (ValueError, UnicodeDecodeError):
            return jsonify(message="GameStats devolvió una respuesta inválida."), 502
    except (URLError, TimeoutError, OSError, ValueError):
        return jsonify(message="GameStats no está disponible. Los eventos quedan pendientes en esta pestaña."), 503


@stats.post("/api/gamestats/events")
def send_event():
    if request.content_length is not None and request.content_length > 16384:
        return jsonify(message="Evento demasiado grande."), 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("gameId") not in ("PACMAN", "RACING"):
        return jsonify(message="Se requiere un evento JSON de PACMAN o RACING."), 400
    return forward("GAMESTATS_INGESTION_URL", "/api/v1/events", payload)


@stats.get("/api/gamestats/pacman/players/<player_id>")
def player_stats(player_id):
    return forward("GAMESTATS_ANALYTICS_URL", "/api/v1/pacman/players/" + quote(player_id, safe=""))


@stats.get("/api/gamestats/matches/<match_id>")
def match_stats(match_id):
    return forward("GAMESTATS_ANALYTICS_URL", "/api/v1/matches/" + quote(match_id, safe=""))
