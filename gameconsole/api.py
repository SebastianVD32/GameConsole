"""API JSON de la consola: partidas de ajedrez y consulta de GameStats."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from .games.chess import ChessMatch, MatchError
from .services import ConsoleServices
from .stats import UpstreamError
from .arcade import EventConflict

api = Blueprint("api", __name__)


def services() -> ConsoleServices:
    return current_app.extensions["console"]


def problem(status: int, message: str):
    return jsonify({"error": message}), status


def chess_payload(match: ChessMatch) -> dict:
    return {**match.snapshot(), "delivery": services().delivery(match.match_id)}


def find_chess_match(match_id: str) -> ChessMatch | None:
    session = services().registry.get(match_id)
    return session if isinstance(session, ChessMatch) else None


@api.post("/ajedrez/partidas")
def create_chess_match():
    body = request.get_json(silent=True) or {}
    try:
        depth = int(body.get("depth", 3))
        match = services().new_chess_match(
            name=str(body.get("name", "Jugador")),
            color=str(body.get("color", "WHITE")).upper(),
            depth=depth,
            control=str(body.get("control", "10+5")),
        )
    except (TypeError, ValueError) as error:
        return problem(400, str(error))
    return jsonify(chess_payload(match)), 201


@api.get("/ajedrez/partidas/<match_id>")
def get_chess_match(match_id: str):
    match = find_chess_match(match_id)
    if match is None:
        return problem(404, "Partida no encontrada")
    return jsonify(chess_payload(match))


@api.post("/ajedrez/partidas/<match_id>/movimientos")
def play_chess_move(match_id: str):
    match = find_chess_match(match_id)
    if match is None:
        return problem(404, "Partida no encontrada")
    body = request.get_json(silent=True) or {}
    try:
        match.play_human_move(str(body.get("move", "")))
    except MatchError as error:
        return jsonify({"error": str(error), "state": chess_payload(match)}), 409
    return jsonify(chess_payload(match))


@api.post("/ajedrez/partidas/<match_id>/abandonar")
def resign_chess_match(match_id: str):
    match = find_chess_match(match_id)
    if match is None:
        return problem(404, "Partida no encontrada")
    try:
        match.resign()
    except MatchError as error:
        return problem(409, str(error))
    return jsonify(chess_payload(match))


@api.get("/partidas")
def list_sessions():
    """Partidas que ejecuta esta consola (vista operativa, no estadística)."""
    sessions = [s.summary() for s in services().registry.sessions()]
    sessions.extend(current_app.extensions["arcade"].summaries())
    return jsonify(sorted(sessions, key=lambda s: s["createdAt"], reverse=True))


@api.post("/arcade/events")
def save_arcade_event():
    request.max_content_length = 16384
    event = request.get_json(silent=True)
    try:
        return jsonify(current_app.extensions["arcade"].append(event)), 202
    except EventConflict as error:
        return problem(409, str(error))
    except (ValueError, TypeError) as error:
        return problem(400, str(error))


@api.post("/arcade/events/batch")
def save_arcade_batch():
    request.max_content_length = 512 * 1024
    events = request.get_json(silent=True)
    try:
        current_app.extensions["arcade"].append_batch(events)
        return jsonify(accepted=True, persisted=True), 202
    except EventConflict as error:
        return problem(409, str(error))
    except (ValueError, TypeError) as error:
        return problem(400, str(error))


@api.get("/arcade/partidas/<match_id>/envio")
def arcade_delivery(match_id):
    status = current_app.extensions["arcade"].status(match_id)
    return (jsonify(status), 200) if status else problem(404, "Partida arcade no encontrada")


@api.post("/arcade/partidas/<match_id>/reintentar")
def retry_arcade_delivery(match_id):
    relay = current_app.extensions["arcade"]
    if relay.status(match_id) is None:
        return problem(404, "Partida arcade no encontrada")
    relay.retry(match_id)
    return jsonify(relay.status(match_id))


@api.get("/estadisticas")
def statistics_overview():
    payload = services().stats.overview()
    if services().dispatcher is not None:
        payload["delivery"] = services().dispatcher.overview()
    return jsonify(payload)


@api.get("/estadisticas/partidas/<match_id>")
def match_statistics(match_id: str):
    try:
        result = services().stats.match_result(match_id)
    except UpstreamError as error:
        return problem(502, str(error))
    if result is None:
        return problem(404, "GameStats aún no tiene resultados de esta partida")
    return jsonify(result)


@api.get("/salud")
def health():
    return jsonify({"console": "ok", "gamestats": services().stats.health()})
