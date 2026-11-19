"""GameConsole: consola web de videojuegos integrada con GameStats."""

from __future__ import annotations

import logging

from flask import Flask

from .services import ConsoleServices, Settings


def create_app(services: ConsoleServices | None = None, settings: Settings | None = None) -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.extensions["console"] = services or ConsoleServices.build(settings or Settings.from_env())

    from gamestats import stats as arcade_bridge  # Pac-Man y carreras (navegador → GameStats)

    from .api import api
    from .web import web

    app.register_blueprint(web)
    app.register_blueprint(arcade_bridge)
    app.register_blueprint(api, url_prefix="/api")
    return app
