# GameConsole

Consola web de videojuegos (Python/Flask): **ajedrez** contra una computadora cuya inteligencia está escrita en **Prolog**, **Pac-Man** y **carreras de circuito**. Todas las partidas envían sus eventos a **GameStats**, y el panel muestra las estadísticas que GameStats calcula.

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
node --test tests/pacman.test.cjs tests/racing.test.cjs tests/delivery.test.cjs   # motores JavaScript (Node 22+)
```

## Despliegue

El pipeline publica la imagen `ghcr.io/sebastianvd32/gameconsole` (`latest` y `sha-…`) en cada push a `main`. El despliegue usa solo imágenes publicadas, sin código fuente:

```powershell
docker compose -f deploy/compose.yaml up -d --wait
```

Requiere que GameStats publique una versión de sus imágenes con los cambios de integración (por defecto `GAMESTATS_VERSION=v1.2.0`).

## CI/CD (`.github/workflows/ci.yml`)

1. **Pruebas**: `docker build --target test` compila la imagen con SWI-Prolog y ejecuta las pruebas Python (reglas, Prolog, eventos, API y puente de Pac-Man); luego Node ejecuta las pruebas de Pac-Man, carreras y entrega de eventos.
2. **Integración**: descarga GameStats (`GAMESTATS_REF`, por defecto `main`), levanta los cuatro servicios con Compose y ejecuta `scripts/smoke_test.py`.
   También verifica dos carreras completas y una regresión de Pac-Man contra Go y Scala.
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
- `ChessEvents`, `PacmanEvents` y `RacingEvents` conocen los tipos y campos exactos que acepta GameStats. Los juegos de Pac-Man y carreras generan el mismo sobre y sus payloads desde sus motores JavaScript; usan el puente HTTP compartido `gamestats.py`.
- `EventDispatcher` mantiene **una cola FIFO por `matchId`** y la drena con un grupo de hilos compartido. Dentro de una partida los eventos se envían en orden, porque GameStats exige la secuencia. Entre partidas, el envío es paralelo. El juego nunca espera a la red.
- Manejo de fallos:
  - Red caída o 5xx: reintentos con espera exponencial; si persisten, la cola se pausa sin perder el orden.
  - 409: el evento ya estaba aceptado, así que se cuenta como entregado.
  - 422 de contrato: se detiene solo esa partida.
  - **Reinicio de GameStats**: Go pierde las partidas en curso. La consola lo detecta y reenvía el historial con los mismos `eventId`.

Eventos de ajedrez: `MATCH_STARTED`, `AI_DECISION` (antes de cada jugada de la IA: profundidad, nodos, evaluación y tiempo de cálculo), `MOVE_PLAYED`, `PIECE_CAPTURED` y `MATCH_FINISHED` (`CHECKMATE`, `RESIGNATION`, `DRAW` o `TIMEOUT`).

### Panel (`/estadisticas`)

El panel consulta GameStats cada 2,5 s a través de `/api/estadisticas` y **no calcula ninguna métrica**:

- **Go** (`/api/v1/summary`): instancias iniciadas, activas y cerradas por juego, y el progreso de las partidas en curso. Los cierres incluyen carreras abortadas.
- **Scala** (`/api/v1/stats`): estadísticas generales y por juego. En ajedrez incluye resultados por motivo, victorias por color, datos por jugador y decisiones de la IA.
- Al terminar una partida, su página muestra el resultado que calculó Scala (`/api/v1/matches/{id}`).

La actualización es por consultas periódicas, no por WebSocket. El progreso de
Go aparece durante el juego; los agregados Scala cambian al procesar un cierre.
El panel distingue carreras completadas y abortadas. Los bloques de historial y
resultado de los juegos consultan Scala cada cinco segundos; no calculan estas
estadísticas en el navegador.

### Varias instancias

Cada partida tiene un `matchId` único. Ajedrez vive en el registro en memoria del proceso y la URL `?partida=<id>` permite abrir su estado. Pac-Man y carreras mantienen las reglas en su pestaña y registran en la consola los eventos recibidos; sus enlaces del listado llevan al panel, sin fingir que otra pestaña puede controlar el mismo estado. El contenedor usa un proceso de gunicorn con 16 hilos. La IA y la entrega de eventos usan grupos de hilos separados.

Los juegos arcade ofrecen **Otra instancia**, que abre una pestaña independiente. `SimulationClock` actualiza las reglas por temporizador y el dibujo usa `requestAnimationFrame`: cambiar de pestaña no pausa la partida. Los retrasos del temporizador se procesan en subpasos con un presupuesto por llamada para no bloquear la interfaz. **P** sigue pausando voluntariamente. En carreras se liberan los pedales al perder el foco. El navegador puede suspender completamente una pestaña o el equipo; no se promete ejecución durante esa suspensión ni recuperación del tablero después de recargar.

### Revisión del enunciado para los dos juegos arcade

| Requisito | Implementación y comprobación |
|---|---|
| Juegos funcionales y programación orientada a objetos | Motores independientes del DOM, clases de reglas, personajes/autos, control y dibujo; pruebas de victoria, derrota y vueltas. |
| Partidas simultáneas e identificadores independientes | UUID por partida/evento, nuevas pestañas, simulación separada del dibujo y envío concurrente por partida. |
| Inicio, desarrollo y final compatibles con GameStats | Contratos PACMAN/RACING sin campos inventados; finales naturales y referencias/secuencias preservadas. |
| Fallos de comunicación sin bloquear otros juegos | Diario SQLite, confirmación después de guardar, trabajadores por partida, reintentos y recuperación del historial si Go pierde su estado. |
| Estadísticas por juego, generales e instancias en vivo | `/estadisticas` consulta Go y Scala; el registro operativo local no calcula métricas estadísticas. |
| Instalación, contenedores, CI/CD y despliegue reproducible | Dockerfile, Compose, volumen persistente y workflow con pruebas e integración real. Docker local comprobado; queda documentar y verificar el entorno de entrega definitivo elegido por el equipo (no se exige que la web sea pública). |
| Demostración en video | Pendiente grabar los tres juegos, concurrencia, Prolog y panel, y añadir el enlace público solicitado (máximo aproximado de 15 minutos). |

Prolog se exige en al menos un juego y ya corresponde a ajedrez. El documento deja las reglas de los juegos a criterio del equipo: no exige boxes, sanciones ni más niveles para los arcade. La extensión RACING `MATCH_ABORTED` registra abandonos sin inventar vueltas ni clasificación y requiere Go y Scala actualizados (ver la referencia de integración más abajo).

## Pac-Man (implementado por el compañero de equipo)

- Un laberinto completo con 213 pastillas, cuatro poderes y tres vidas. Ganas al recoger todas las pastillas; pierdes al agotar las vidas.
- Flechas o WASD para moverte, P para pausar; también hay botones direccionales para pantallas táctiles. Pulsa **Jugar ahora** para comenzar.
- Un giro bloqueado queda solicitado hasta la siguiente intersección donde sea posible. El personaje continúa por su dirección actual mientras el camino esté libre.
- Cada pastilla vale 10 puntos; cada poder vale 50 y dura 8 segundos reales. Dentro del mismo efecto, los cuatro fantasmas distintos valen 200, 400, 800 y 1600 puntos. El reloj del poder sigue avanzando durante la pausa para respetar los timestamps del contrato de GameStats.
- Los fantasmas usan búsqueda de caminos en JavaScript: Blinky persigue, Pinky anticipa, Inky alterna patrulla y persecución, Clyde se retira cuando estás cerca. Durante un poder se alejan. Un fantasma capturado permanece fuera del tablero hasta que termina ese efecto.
- **Nueva partida** finaliza la anterior con motivo `RESTARTED` y prepara otra con UUID nuevo. Pausar y continuar conservan el identificador. No hay conexión con Prolog.
- Puedes abrir varias pestañas con estados independientes; la simulación continúa al cambiar de pestaña. Usa P si necesitas detenerla. No se guarda el laberinto para reanudar después de recargar.

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

`GAMESTATS_INGEST_URL` es la variable compartida de ingestión y tiene prioridad; `GAMESTATS_INGESTION_URL` se conserva como alias compatible. Son URLs base de servicios controlados por el equipo, sin `/api/v1`. Flask reenvía los eventos a `POST /api/v1/events`, consulta `GET /api/v1/pacman/players/{playerId}` para el historial de Pac-Man y `GET /api/v1/matches/{matchId}` para carreras. La comunicación desde el navegador pasa por Flask, por lo que no requiere habilitar CORS en GameStats. Los timeouts de red y las solicitudes asíncronas evitan bloquear el juego.

#### Eventos y fallos

Se envía exactamente el sobre exigido: `eventId`, `timestamp` UTC, `gameId: PACMAN`, `gameVersion: 1.0`, `matchId`, `sequence`, `playerId`, `type`, `data`. La secuencia comienza en 1. Inicio y final llevan `playerId: null`; las acciones llevan el jugador registrado en el inicio. El jugador anónimo se conserva en `localStorage` para consultar su historial.

Se generan `MATCH_STARTED`, `PELLET_EATEN`, `POWER_UP_COLLECTED`, `GHOST_EATEN`, `LIFE_LOST`, `LEVEL_COMPLETED` y `MATCH_FINISHED`. No se envían eventos de movimiento o pausa que ese contrato rechazaría. Los poderes se referencian por el ID del evento original. Un efecto no admite dos capturas del mismo fantasma.

El navegador envía a `POST /api/arcade/events`. La consola responde `202` con `persisted: true` solo después del commit SQLite: eso significa **guardado en consola**, no aceptado todavía por Go. El diario conserva el JSON original, con unicidad de `eventId` y `(matchId, sequence)`, identidad estable y timestamps UTC ordenados. `ArcadeRelay` drena una cola por partida usando un grupo de trabajadores, sin hacer red dentro de la petición del juego.

La UI consulta `/api/arcade/partidas/{matchId}/envio` y distingue lo guardado de lo **aceptado por GameStats**. Red caída, 5xx o 429 conservan los pendientes y se reintentan a los cinco segundos; `409 DUPLICATE_EVENT` es idempotente. Los rechazos de contrato detienen solo esa partida y muestran el error. Si Go olvida la partida, se reenvía el historial con sus IDs originales. El botón de reintento también reactiva la cola del servidor.

El diario está en `data/arcade.sqlite3` al ejecutar localmente, o en `/data/arcade/events.sqlite3` con el volumen `arcade-events` de Compose. `GAMECONSOLE_ARCADE_DB` permite cambiar la ruta. Los eventos confirmados como guardados sobreviven al cierre de la pestaña y al reinicio de la consola. No se borran al terminar la partida: el historial permite re-sincronizar. Usa una sola instancia de consola por volumen, como en la configuración actual.

Antes de recibir esa confirmación, los pendientes siguen en `sessionStorage`. `pagehide` intenta entregarlos con `sendBeacon` en lotes idempotentes y registrar el final de Pac-Man. Un cierre forzado antes de que la consola los guarde aún puede perder esos últimos eventos; no se presenta el envío de cierre como garantizado. El archivo exportado de una partida en curso es parcial y todavía no tiene `MATCH_FINISHED`.

El botón **Descargar eventos JSONL** exporta el formato que acepta el cargador Go (`-input archivo.jsonl -serve=false`). Usa un servicio de prueba limpio si esos IDs ya fueron recibidos, ya que Go los deduplica.

#### Historial real frente a estado local

La puntuación, vidas y tiempo en el tablero son estado de la partida, necesario para jugar. El bloque **Tu historial** consulta Scala cada cinco segundos; no calcula sus estadísticas localmente. Sin GameStats, puedes jugar y descargar los eventos, y la pantalla muestra el estado pendiente.

GameStats persiste y analiza Pac-Man al recibir `MATCH_FINISHED`; por eso su historial cambia al finalizar, aunque los eventos se envían mientras juegas. Esta API no ofrece estadísticas analíticas parciales de una partida en curso. Las partidas de Pac-Man también aparecen en el panel global `/estadisticas` (instancias y progreso desde Go, agregados desde Scala).

### Pruebas de Pac-Man

```powershell
python -m unittest discover -s tests -v
node --test tests/pacman.test.cjs tests/racing.test.cjs tests/delivery.test.cjs
```

Las pruebas de Node 22+ usan el motor real y verifican alcanzabilidad, movimiento, pausa, poderes, puntuación, victoria, derrota, aislamiento y reintentos. Las pruebas Python cubren rutas, reenvío HTTP, consulta de estadísticas y fallos. El workflow existente ejecuta ambas suites.

Para comprobar el contrato contra el **servicio Go real**, con Go 1.24+, Node 22+ y el repositorio GameStats disponible:

```powershell
python scripts/verify_pacman_integration.py ../GameStats
```

El script levanta Go y Flask en puertos temporales, envía dos partidas concurrentes (una victoria y otra con captura de cuatro fantasmas y pérdida de tres vidas), comprueba todos los eventos aceptados y detiene sus procesos. Usa archivos temporales; no consulta Scala. Para comprobar también el procesamiento Scala, inicia los servicios completos y ejecuta `node tests/gamestats.integration.cjs`; luego consulta el historial en la interfaz.

## Carreras

**Circuito Neón** es una carrera arcade de tres vueltas en un circuito de 1500 metros contra Vector, Apex y Turbo. El auto del jugador es cian. La salida tiene una cuenta regresiva de tres segundos; cada rival controla su aceleración, frenado y carril mediante reglas JavaScript, sin conexión con Prolog.

- Mantén **↑ / W** para acelerar y **↓ / S** para frenar. **← / A** y **→ / D** desplazan el auto hacia su izquierda o derecha dentro del circuito, tomando como referencia la orientación del automóvil. El auto sigue la trayectoria del circuito; no es un simulador de dirección libre.
- **P** o el botón superior pausa y continúa. Los controles en pantalla admiten pulsación sostenida y varios dedos, de modo que puedes acelerar y girar al mismo tiempo.
- Las curvas cerradas producen deriva al exceder la velocidad segura. El césped reduce la velocidad, y los contactos frenan a ambos autos durante un breve intervalo. Se puede regresar a la pista incluso desde velocidad cero. No hay atajos que salten vueltas.
- El cronómetro excluye las pausas. Cada cruce de meta registra una vuelta, su tiempo entero en milisegundos y el puesto de cruce de esa vuelta. El juego termina cuando los cuatro autos completan las tres vueltas; si llegas primero, los rivales continúan hasta cerrar la clasificación.
- El orden final usa la suma de los tiempos de vuelta y desempata por el puesto de la última vuelta, igual que GameStats cuando no existen sanciones. Esta clasificación es parte de las reglas del juego. El bloque **Resultado oficial** consulta los datos procesados por Scala, incluyendo tu mejor vuelta y posición final.
- **Retirarme** cierra la carrera con `MATCH_ABORTED` y motivo `USER_QUIT`. **Nueva carrera** cierra la anterior con `RESTARTED` y prepara otra identidad. Al cerrar o recargar se intenta enviar `PAGE_CLOSED`. Si aún no pasó la cuenta regresiva no existe una partida remota que cerrar. Un cierre forzado antes de guardar el evento no garantiza su entrega.
- Al perder el foco se liberan los controles, mientras la carrera continúa en segundo plano. Usa P para pausar voluntariamente. Cada pestaña conserva su estado independiente; el estado de conducción no se recupera tras recargar.

### Clases y eventos de carreras

Referencia de integración: GameStats commit
`6243151d7c82919720742056f15a22f2d372482e` (rama
`codex/racing-abort-contract`). El workflow usa esta revisión por defecto y
conserva los overrides `gamestats_ref`/`GAMESTATS_REF`. Actualiza el checkout
externo antes de reconstruir ambos servicios:

```powershell
git -C ../GameStats fetch origin
git -C ../GameStats switch --detach 6243151d7c82919720742056f15a22f2d372482e
docker compose up --build --wait -d
```

Ejecuta el cambio de revisión con el checkout externo limpio; conserva cualquier
trabajo local pendiente. El comando Compose se ejecuta desde GameConsole y usa
`GAMESTATS_DIR` si el checkout está en otra ubicación. El contrato completo está
en `Docs/contrato-abandono-carreras.md` de esa revisión de GameStats.
La ampliación se revisa en [GameStats PR #6](https://github.com/SebastianVD32/GameStats/pull/6);
todavía no forma parte de `main` mientras ese PR siga abierto.

`static/js/racing-engine.js` contiene `Circuit` (trayectoria cerrada interpolada y geometría), `RaceCar` (velocidad, desplazamiento y tiempos), `RivalDriver` (conducción y adelantamientos) y `RacingGame` (salida, vueltas, contactos, pausa y clasificación). La física avanza en subpasos de hasta 1/120 de segundo. `static/js/racing.js` contiene `CircuitRenderer` y `RacingController`, responsables del dibujo, teclado, controles táctiles y presentación.

El juego emite `MATCH_STARTED`, `LAP_COMPLETED` para cada uno de los cuatro pilotos y `MATCH_FINISHED`: una carrera completa de tres vueltas produce 14 eventos. Un abandono sustituye el final por `MATCH_ABORTED`, con `playerId: null` y `data: {"reason": "USER_QUIT" | "RESTARTED" | "PAGE_CLOSED"}`. Se utiliza `gameId: RACING`, `gameVersion: 1.0`, UUID por partida y evento, secuencias continuas y timestamps UTC que no retroceden. No se implementaron boxes ni sanciones; los contactos y salidas de pista afectan físicamente al tiempo de vuelta.

Scala devuelve `status: ABORTED`, motivo, duración y `driverProgress` con las vueltas reales, su tiempo acumulado y boxes abiertos. No asigna ganador ni clasificación. `general.processedMatches` incluye todos los cierres; `completedMatches` excluye abandonos. `games.RACING.abortedMatches` y `abortsByReason` los cuentan por separado; los récords y promedios de carreras usan solo carreras completadas. El formato de los resultados completos anteriores se conserva.

La cola de carreras usa `gameconsole.racing.pending.v1` y la de Pac-Man conserva su clave anterior, evitando mezclar pendientes al navegar entre ambos. El bloque oficial consulta `GET /api/v1/matches/{matchId}` de Scala a través de Flask cada cinco segundos después del final o abandono, hasta recibir el resultado. Si GameStats está desconectado, la conducción sigue disponible y los eventos quedan pendientes.


### Verificación de carreras

Para carreras y una regresión de Pac-Man, con los mismos requisitos:

```powershell
python scripts/verify_racing_integration.py ../GameStats
```

Esta verificación envía seis partidas en paralelo: una carrera ganada, otra perdida, tres abandonos (uno con una vuelta real) y una partida de Pac-Man. Go recibe los eventos reales de los motores y se comprueba que su registro coincida y que los cierres salgan de las partidas activas. No requiere Docker ni Scala. Para verificar también tiempos, clasificación, progreso abortado y contadores oficiales con los servicios completos ya iniciados:

```powershell
$env:VERIFY_SCALA = '1'
node tests/racing.integration.cjs
```

`CONSOLE_URL` y `GAMESTATS_INGESTION_URL` permiten cambiar los endpoints de esas pruebas. La consola debe tener configuradas las URLs de Go y Scala correspondientes. Los escenarios automáticos usan un piloto de prueba que suministra controles al mismo motor; ese piloto no existe en la interfaz del jugador.
