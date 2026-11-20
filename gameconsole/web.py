"""Páginas HTML de la consola."""

from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template

from .catalog import GAMES
from .services import DIFFICULTIES, TIME_CONTROLS

web = Blueprint("web", __name__)


def _context(**extra):
    services = current_app.extensions["console"]
    active = [s.summary() for s in services.registry.sessions() if not s.is_finished]
    active.extend(s for s in current_app.extensions["arcade"].summaries() if not s["finished"])
    active = sorted(active, key=lambda s: s["createdAt"], reverse=True)[:6]
    return {"games": GAMES, "active_sessions": active, **extra}


@web.get("/")
def dashboard():
    return render_template("dashboard.html", page="dashboard", **_context())


@web.get("/estadisticas")
def statistics():
    return render_template("stats.html", page="stats", **_context())


@web.get("/juegos/<game_id>")
def game(game_id: str):
    selected = GAMES.get(game_id)
    if selected is None:
        abort(404)
    if game_id == "ajedrez":
        return render_template("chess.html", page="games", game=selected, game_id=game_id,
                               difficulties=DIFFICULTIES, time_controls=list(TIME_CONTROLS), **_context())
    if game_id in ("pacman", "carreras"):
        template = "pacman.html" if game_id == "pacman" else "racing.html"
        return render_template(template, page="games", game=selected, game_id=game_id, **_context())
    return render_template("game.html", page="games", game=selected, game_id=game_id, **_context())


@web.get("/healthz")
def healthz():
    return {"status": "ok"}


@web.app_errorhandler(404)
def not_found(_error):
    return render_template("404.html", page="", **_context()), 404
