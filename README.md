# GameConsole

Consola web de videojuegos (Python/Flask): **ajedrez** contra una computadora cuya inteligencia está escrita en **Prolog**, **Pac-Man** y un juego de carreras (en desarrollo). Todas las partidas envían sus eventos a **GameStats**, y el panel muestra las estadísticas que GameStats calcula.

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
node --test tests/pacman.test.cjs tests/delivery.test.cjs   # Pac-Man (Node 22+)
```

## Despliegue

El pipeline publica la imagen `ghcr.io/sebastianvd32/gameconsole` (`latest` y `sha-…`) en cada push a `main`. El despliegue usa solo imágenes publicadas, sin código fuente:

```powershell
docker compose -f deploy/compose.yaml up -d --wait
```

Requiere que GameStats publique una versión de sus imágenes con los cambios de integración (por defecto `GAMESTATS_VERSION=v1.2.0`).

## CI/CD (`.github/workflows/ci.yml`)

1. **Pruebas**: `docker build --target test` compila la imagen con SWI-Prolog y ejecuta las pruebas Python (reglas, Prolog, eventos, API y puente de Pac-Man); luego Node ejecuta las pruebas de Pac-Man.
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

## Pac-Man (implementado por el compañero de equipo)

- Un laberinto completo con 213 pastillas, cuatro poderes y tres vidas. Ganas al recoger todas las pastillas; pierdes al agotar las vidas.
- Flechas o WASD para moverte, P para pausar; también hay botones direccionales para pantallas táctiles. Pulsa **Jugar ahora** para comenzar.
- Un giro bloqueado queda solicitado hasta la siguiente intersección donde sea posible. El personaje continúa por su dirección actual mientras el camino esté libre.
- Cada pastilla vale 10 puntos; cada poder vale 50 y dura 8 segundos reales. Dentro del mismo efecto, los cuatro fantasmas distintos valen 200, 400, 800 y 1600 puntos. El reloj del poder sigue avanzando durante la pausa para respetar los timestamps del contrato de GameStats.
- Los fantasmas usan búsqueda de caminos en JavaScript: Blinky persigue, Pinky anticipa, Inky alterna patrulla y persecución, Clyde se retira cuando estás cerca. Durante un poder se alejan. Un fantasma capturado permanece fuera del tablero hasta que termina ese efecto.
- **Nueva partida** finaliza la anterior con motivo `RESTARTED` y prepara otra con UUID nuevo. Pausar y continuar conservan el identificador. No hay conexión con Prolog.
- Puedes abrir varias pestañas con estados y colas independientes. Al ocultar una pestaña se pausa su juego automáticamente; varias ventanas visibles pueden jugar al mismo tiempo. No se guarda el laberinto para reanudar después de recargar.

### Organización orientada a objetos

`static/js/pacman-engine.js` contiene `Maze` (topología y pastillas), `Actor` (posición y movimiento), `Ghost` (decisiones) y `PacmanGame` (reglas, estado y ciclo de vida). No depende del DOM. `static/js/pacman.js` contiene `PacmanRenderer` y `PacmanController`, responsables de dibujo, entradas y presentación. `EventDelivery`, en `static/js/gamestats.js`, administra el envío sin bloquear el juego. Flask sirve la interfaz y funciona como puente HTTP para GameStats.

### Conectar GameStats (Pac-Man)

Referencia verificada: [GameStats](https://github.com/SebastianVD32/GameStats), commit `b86e1838eb6ae2cc709ea7a8fd2c61b48f170b6a` de `main` (v1.1.0). Se siguieron `Docs/contrato-pacman.md`, `Docs/contrato-eventos-go.md` y las implementaciones Go/Scala. No se necesita copiar sus fuentes dentro de GameConsole.

En otra carpeta, descarga GameStats y levanta sus servicios según su README. Con Docker Desktop iniciado:

```powershell
git clone https://github.com/SebastianVD32/GameStats.git ../GameStats
Set-Location ../GameStats
docker compose up --build go-ingestion scala-analysis
```

La consola usa por defecto Go en `http://127.0.0.1:8080` y Scala en `http://127.0.0.1:8081`. Si cambias los puertos, define estas variables **antes de iniciar Flask**:

```powershell
$env:GAMESTATS_INGESTION_URL = 'http://127.0.0.1:8080'
$env:GAMESTATS_ANALYTICS_URL = 'http://127.0.0.1:8081'
python app.py
```

Son URLs base de servicios controlados por el equipo, sin `/api/v1`. Flask reenvía los eventos a `POST /api/v1/events` y consulta `GET /api/v1/pacman/players/{playerId}`. La comunicación desde el navegador pasa por Flask, por lo que no requiere habilitar CORS en GameStats. Los timeouts de red y las solicitudes asíncronas evitan bloquear el juego.

#### Eventos y fallos

Se envía exactamente el sobre exigido: `eventId`, `timestamp` UTC, `gameId: PACMAN`, `gameVersion: 1.0`, `matchId`, `sequence`, `playerId`, `type`, `data`. La secuencia comienza en 1. Inicio y final llevan `playerId: null`; las acciones llevan el jugador registrado en el inicio. El jugador anónimo se conserva en `localStorage` para consultar su historial.

Se generan `MATCH_STARTED`, `PELLET_EATEN`, `POWER_UP_COLLECTED`, `GHOST_EATEN`, `LIFE_LOST`, `LEVEL_COMPLETED` y `MATCH_FINISHED`. No se envían eventos de movimiento o pausa que ese contrato rechazaría. Los poderes se referencian por el ID del evento original. Un efecto no admite dos capturas del mismo fantasma.

Cada partida tiene una cola ordenada y una sola solicitud en curso; partidas distintas pueden enviar en paralelo. Los fallos de red y errores 5xx se reintentan a los cinco segundos conservando IDs y secuencias. El `409 DUPLICATE_EVENT` confirma un reenvío ya recibido. Los errores de validación conservan el evento y detienen esa cola hasta un reintento manual; se muestran en pantalla.

Los eventos pendientes se conservan en `sessionStorage` para reintentar al recargar la misma pestaña. Si el navegador bloquea el almacenamiento, se conservan en memoria y se informa. **Cerrar definitivamente la pestaña puede perder los pendientes**; no se implementó una cola durable en el servidor. `pagehide` intenta registrar la finalización, pero un cierre forzado o corte del proceso no garantiza enviarla. Descarga el JSONL antes de cerrar si necesitas conservar el registro. El archivo de una partida aún activa es parcial: no tiene `MATCH_FINISHED` hasta finalizarla.

El botón **Descargar eventos JSONL** exporta el formato que acepta el cargador Go (`-input archivo.jsonl -serve=false`). Usa un servicio de prueba limpio si esos IDs ya fueron recibidos, ya que Go los deduplica.

#### Historial real frente a estado local

La puntuación, vidas y tiempo en el tablero son estado de la partida, necesario para jugar. El bloque **Tu historial** consulta Scala cada cinco segundos; no calcula sus estadísticas localmente. Sin GameStats, puedes jugar y descargar los eventos, y la pantalla muestra el estado pendiente.

La versión consultada de GameStats persiste y analiza partidas al recibir `MATCH_FINISHED`; por eso su historial cambia al finalizar, aunque los eventos se envían mientras juegas. Esta API no ofrece estadísticas analíticas parciales de una partida en curso. Las partidas de Pac-Man también aparecen en el panel global `/estadisticas` (instancias y progreso desde Go, agregados desde Scala).

### Pruebas de Pac-Man

```powershell
python -m unittest discover -s tests -v
node --test tests/pacman.test.cjs tests/delivery.test.cjs
```

Las pruebas de Node 22+ usan el motor real y verifican alcanzabilidad, movimiento, pausa, poderes, puntuación, victoria, derrota, aislamiento y reintentos. Las pruebas Python cubren rutas, reenvío HTTP, consulta de estadísticas y fallos. El workflow existente ejecuta ambas suites.

Para comprobar el contrato contra el **servicio Go real**, con Go 1.24+, Node 22+ y el repositorio GameStats disponible:

```powershell
python scripts/verify_pacman_integration.py ../GameStats
```

El script levanta Go y Flask en puertos temporales, envía dos partidas concurrentes (una victoria y otra con captura de cuatro fantasmas y pérdida de tres vidas), comprueba todos los eventos aceptados y detiene sus procesos. Usa archivos temporales; no consulta Scala. Para comprobar también el procesamiento Scala, inicia los servicios completos y ejecuta `node tests/gamestats.integration.cjs`; luego consulta el historial en la interfaz.

## Integrar Carreras

1. Crear una subclase de `GameSession` (`gameconsole/games/base.py`) con la lógica del juego.
2. Crear el flujo de eventos: `PacmanEvents(EventStream("PACMAN", "1.0", match_id, services.sink))`.
3. Llamar a sus métodos (`pellet_eaten`, `lap_completed`, …). El despachador se encarga del envío.
4. Registrar la sesión en `services.registry` y marcar el juego como `playable` en `gameconsole/catalog.py`.
