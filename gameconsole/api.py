"""API JSON de la consola: partidas de ajedrez y consulta de GameStats."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from .games.chess import ChessMatch, MatchError
from .services import ConsoleServices
from .stats import UpstreamError

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
    return jsonify([s.summary() for s in services().registry.sessions()])


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
