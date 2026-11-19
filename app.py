"""Punto de entrada de GameConsole (desarrollo: ``python app.py``)."""

from gameconsole import create_app

app = create_app()


if __name__ == "__main__":
    # threaded=True: cada pestaña/partida se atiende en su propio hilo.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
