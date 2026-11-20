# GameConsole: Flask + SWI-Prolog (janus-swi) en una sola imagen.
# La imagen oficial de SWI-Prolog trae el intérprete y sus cabeceras, necesarias
# para compilar el puente janus-swi entre Python y Prolog.
FROM swipl:9.2.9 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-dev gcc curl \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py gamestats.py ./
COPY gunicorn.conf.py ./
COPY gameconsole ./gameconsole
COPY templates ./templates
COPY static ./static

# Etapa de pruebas: reglas, motor Prolog, eventos y API (docker build --target test .)
FROM base AS test
COPY tests ./tests
RUN python -m unittest discover -s tests -t . -v

FROM base AS runtime
RUN useradd --system --uid 10001 --no-create-home gameconsole \
    && mkdir -p /data/arcade && chown gameconsole /data/arcade
USER gameconsole
EXPOSE 5000
ENV GAMESTATS_INGEST_URL=http://gamestats-go:8080 \
    GAMESTATS_INGESTION_URL=http://gamestats-go:8080 \
    GAMESTATS_ANALYTICS_URL=http://gamestats-scala:8081 \
    GAMECONSOLE_ARCADE_DB=/data/arcade/events.sqlite3
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD curl --fail --silent "http://127.0.0.1:${PORT:-5000}/healthz" || exit 1
# Un solo proceso (el registro de partidas vive en memoria) con varios hilos:
# cada pestaña/partida se atiende en paralelo y la IA corre en su propio grupo de hilos.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
