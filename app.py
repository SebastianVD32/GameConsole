from flask import Flask, abort, render_template


app = Flask(__name__)


GAMES = {
    "ajedrez": {
        "name": "Ajedrez",
        "short_name": "Ajedrez",
        "eyebrow": "Jugador vs. IA",
        "description": "Desafía al motor lógico y revisa cada decisión calculada por Prolog.",
        "icon": "♞",
        "accent": "violet",
        "status": "En curso",
        "session": "AJ-1042",
    },
    "pacman": {
        "name": "Pac-Man",
        "short_name": "Pac-Man",
        "eyebrow": "Arcade individual",
        "description": "Recorre el laberinto, supera tu puntuación y evita a los fantasmas.",
        "icon": "●",
        "accent": "amber",
        "status": "En pausa",
        "session": "PA-2087",
    },
    "carreras": {
        "name": "Juego de carreras",
        "short_name": "Carreras",
        "eyebrow": "Contrarreloj",
        "description": "Completa el circuito y mejora tus tiempos vuelta tras vuelta.",
        "icon": "↗",
        "accent": "cyan",
        "status": "Disponible",
        "session": "CA-3011",
    },
}


@app.get("/")
def dashboard():
    return render_template("dashboard.html", games=GAMES, page="dashboard")


@app.get("/juegos/<game_id>")
def game(game_id: str):
    selected_game = GAMES.get(game_id)
    if selected_game is None:
        abort(404)
    return render_template(
        "game.html",
        game=selected_game,
        game_id=game_id,
        games=GAMES,
        page="games",
    )


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html", games=GAMES, page=""), 404


if __name__ == "__main__":
    app.run(debug=True)
