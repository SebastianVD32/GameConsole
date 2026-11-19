# GameConsole

Consola web de videojuegos (Python/Flask) con un ajedrez contra la computadora cuya inteligencia está escrita en **Prolog**. Todas las partidas envían sus eventos a **GameStats**, y el panel muestra las estadísticas que GameStats calcula.

```text
Navegador (varias pestañas = varias instancias)
   │  HTTP/JSON
   ▼
GameConsole (Flask, un proceso con hilos)
   ├─ Juegos POO ──────────── games/chess: Board, Piece…, ChessClock, Player, ChessMatch
   ├─ IA ─────── janus-swi ─▶ SWI-Prolog: chess_ai.pl (negamax alfa-beta + quiescencia)
   ├─ Eventos ─ EventStream ─▶ EventDispatcher (cola por partida, hilos, reintentos)
   │                                 │ POST /api/v1/events
   │                                 ▼
   │                         GameStats Go (valida, agrupa) ──▶ GameStats Scala (calcula)
   └─ Panel ── GET /api/v1/summary (Go) + GET /api/v1/stats (Scala) ◀──┘
```

## Ejecución integrada con Docker (recomendada)

Requisitos: Docker con Compose y el repositorio de GameStats clonado **al lado** de este:

```text
Lenguages/
├─ GameConsole/
└─ GameStats/      ← rama con AI_DECISION, /api/v1/summary y /api/v1/stats
```

```powershell
docker compose up --build --wait -d
```

- Consola: <http://localhost:5000>
- GameStats Go: <http://localhost:8080/healthz> · Scala: <http://localhost:8081/healthz>

Si GameStats está en otra carpeta: `$env:GAMESTATS_DIR = 'C:\ruta\GameStats'`. Si los puertos 8080/8081 están ocupados: `$env:GAMESTATS_GO_PORT = '18080'; $env:GAMESTATS_SCALA_PORT = '18081'`. Para detener todo: `docker compose down`. Agrega `--volumes` si también quieres borrar las estadísticas guardadas.

Prueba de humo, con 3 partidas en paralelo contra la IA y verificación de GameStats:

```powershell
python scripts/smoke_test.py http://127.0.0.1:5000 --matches 3
```

## Desarrollo local sin Docker

Requisitos: Python 3.12+ y [SWI-Prolog](https://www.swi-prolog.org/download/stable) 9.x en el `PATH`. GameStats puede correr con Docker desde su propio repositorio.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install Flask==3.1.2 janus-swi==1.5.3      # gunicorn solo se usa en el contenedor
$env:GAMESTATS_INGEST_URL = 'http://localhost:8080'
$env:GAMESTATS_ANALYTICS_URL = 'http://localhost:8081'
python app.py
```

Pruebas, que incluyen las de Prolog cuando SWI-Prolog está instalado:

```powershell
python -m unittest discover -s tests -t . -v
```

## Despliegue

El pipeline publica la imagen `ghcr.io/sebastianvd32/gameconsole` (`latest` y `sha-…`) en cada push a `main`. El despliegue usa solo imágenes publicadas, sin código fuente:

```powershell
docker compose -f deploy/compose.yaml up -d --wait
```

Requiere que GameStats publique una versión de sus imágenes con los cambios de integración (por defecto `GAMESTATS_VERSION=v1.2.0`).

## CI/CD (`.github/workflows/ci.yml`)

1. **Pruebas**: `docker build --target test` compila la imagen con SWI-Prolog y ejecuta todas las pruebas: reglas, Prolog, eventos y API.
2. **Integración**: descarga GameStats (`GAMESTATS_REF`, por defecto `main`), levanta los cuatro servicios con Compose y ejecuta `scripts/smoke_test.py`.
3. **Publicación** (solo `main`): imagen `runtime` en GHCR.

## Decisiones técnicas

### Ajedrez orientado a objetos (`gameconsole/games/chess/`)

| Clase | Responsabilidad |
|---|---|
| `Piece` (abstracta) → `LeaperPiece` (`Knight`, `King`), `SlidingPiece` (`Bishop`, `Rook`, `Queen`), `Pawn` | Cada pieza sabe cómo se mueve y qué casillas ataca (polimorfismo). |
| `Board` | Posición completa, legalidad (jaque, enroque, captura al paso, promoción), FEN. |
| `CastlingRights`, `Move`, `MoveOutcome` | Valores inmutables. |
| `ChessClock`, `TimeControl` | Reloj con incremento que produce exactamente los valores que exige GameStats. |
| `Player` → `HumanPlayer`, `ComputerPlayer` | El jugador automatizado delega en un `ChessEngine`. |
| `ChessEngine` → `PrologChessEngine` | Puente con Prolog. Se puede sustituir por otro motor. |
| `GameSession` → `ChessMatch` | Ciclo de vida de una instancia: turnos, fin de partida, emisión de eventos. |

Las reglas se validan con pruebas *perft*, que comparan el conteo de movimientos legales con los valores de referencia de cinco posiciones difíciles.

### Inteligencia en Prolog (`gameconsole/games/chess/ai/chess_ai.pl`)

- Python envía la posición en **FEN** y Prolog responde con el movimiento (`e7e8q`), la evaluación y los nodos explorados.
- Prolog tiene su **propio generador de movimientos legales** y coincide con el de Python en todas las pruebas *perft*.
- **Negamax con poda alfa-beta** a la profundidad elegida (1 a 4) y **búsqueda de quiescencia** sobre capturas para no cortar en mitad de un intercambio.
- **Ordenamiento MVV-LVA**: primero se revisan las capturas más valiosas hechas con la pieza más barata, lo que hace más eficaz la poda.
- **Evaluación**: material más tablas de posición por pieza. El mate se puntúa según la distancia, así que prefiere el mate más rápido.
- Janus asocia cada hilo de Python a un hilo de Prolog, por lo que varias partidas pueden calcular a la vez.

### Eventos y envío concurrente (`gameconsole/events/`)

- `EventStream`, uno por partida, genera el sobre común de GameStats: `eventId` UUID, `sequence` continua desde 1 y `timestamp` UTC que nunca retrocede.
- `ChessEvents`, `PacmanEvents` y `RacingEvents` conocen los tipos y campos exactos que acepta GameStats. Los de Pac-Man y Carreras quedan listos para esos juegos.
- `EventDispatcher` mantiene **una cola FIFO por `matchId`** y la drena con un grupo de hilos compartido. Dentro de una partida los eventos se envían en orden, porque GameStats exige la secuencia. Entre partidas, el envío es paralelo. El juego nunca espera a la red.
- Manejo de fallos:
  - Red caída o 5xx: reintentos con espera exponencial; si persisten, la cola se pausa sin perder el orden.
  - 409: el evento ya estaba aceptado, así que se cuenta como entregado.
  - 422 de contrato: se detiene solo esa partida.
  - **Reinicio de GameStats**: Go pierde las partidas en curso. La consola lo detecta y reenvía el historial con los mismos `eventId`.

Eventos de ajedrez: `MATCH_STARTED`, `AI_DECISION` (antes de cada jugada de la IA: profundidad, nodos, evaluación y tiempo de cálculo), `MOVE_PLAYED`, `PIECE_CAPTURED` y `MATCH_FINISHED` (`CHECKMATE`, `RESIGNATION`, `DRAW` o `TIMEOUT`).

### Panel (`/estadisticas`)

El panel consulta GameStats cada 2,5 s a través de `/api/estadisticas` y **no calcula ninguna métrica**:

- **Go** (`/api/v1/summary`): instancias iniciadas, activas y finalizadas por juego, y el progreso de las partidas en curso.
- **Scala** (`/api/v1/stats`): estadísticas generales y por juego. En ajedrez incluye resultados por motivo, victorias por color, datos por jugador y decisiones de la IA.
- Al terminar una partida, su página muestra el resultado que calculó Scala (`/api/v1/matches/{id}`).

### Varias instancias

Cada partida tiene un `matchId` (`chess-<uuid>`) y vive en el registro en memoria del proceso. La URL `?partida=<id>` permite abrir cada instancia en su propia pestaña. El contenedor usa un solo proceso de gunicorn con 16 hilos, porque el registro es en memoria. La IA usa su propio grupo de hilos y el envío de eventos el suyo.

## Integrar Pac-Man o Carreras

1. Crear una subclase de `GameSession` (`gameconsole/games/base.py`) con la lógica del juego.
2. Crear el flujo de eventos: `PacmanEvents(EventStream("PACMAN", "1.0", match_id, services.sink))`.
3. Llamar a sus métodos (`pellet_eaten`, `lap_completed`, …). El despachador se encarga del envío.
4. Registrar la sesión en `services.registry` y marcar el juego como `playable` en `gameconsole/catalog.py`.
