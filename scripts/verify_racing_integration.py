"""Start isolated Go + Flask and verify two full races plus a Pac-Man regression.

Usage: .venv/Scripts/python scripts/verify_racing_integration.py ../GameStats
"""
from verify_pacman_integration import main


if __name__ == "__main__":
    main(test_file="tests/racing.integration.cjs", game_path="/juegos/carreras")
