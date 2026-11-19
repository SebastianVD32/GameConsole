"""Catálogo de juegos que muestra la consola."""

GAMES = {
    "ajedrez": {
        "name": "Ajedrez",
        "short_name": "Ajedrez",
        "game_id": "CHESS",
        "eyebrow": "Jugador vs. IA Prolog",
        "description": "Desafía al motor lógico: negamax con poda alfa-beta escrito en Prolog.",
        "icon": "♞",
        "accent": "violet",
        "status": "Disponible",
        "playable": True,
    },
    "pacman": {
        "name": "Pac-Man",
        "short_name": "Pac-Man",
        "game_id": "PACMAN",
        "eyebrow": "Arcade individual",
        "description": "Recorre el laberinto, supera tu puntuación y evita a los fantasmas.",
        "icon": "●",
        "accent": "amber",
        "status": "Disponible",
        "playable": True,
    },
    "carreras": {
        "name": "Juego de carreras",
        "short_name": "Carreras",
        "game_id": "RACING",
        "eyebrow": "Carrera de circuito",
        "description": "Compite contra tres rivales, domina las curvas y conquista el podio.",
        "icon": "↗",
        "accent": "cyan",
        "status": "Disponible",
        "playable": True,
    },
}

GAME_NAMES = {game["game_id"]: game["name"] for game in GAMES.values()}
