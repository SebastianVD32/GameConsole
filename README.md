# GameConsole

Consola web en Python/Flask. Pac-Man es jugable y genera los eventos del contrato real de GameStats. Ajedrez y carreras conservan sus pantallas de demostración; se desarrollarán por separado.

## Ejecutar localmente

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Abre `http://127.0.0.1:5000/juegos/pacman`. Requiere Python 3.12+ y un navegador moderno con Canvas. Node solo se necesita para ejecutar las pruebas.

## Pac-Man

- Un laberinto completo con 213 pastillas, cuatro poderes y tres vidas. Ganas al recoger todas las pastillas; pierdes al agotar las vidas.
- Flechas o WASD para moverte, P para pausar; también hay botones direccionales para pantallas táctiles. Pulsa **Jugar ahora** para comenzar.
- Un giro bloqueado queda solicitado hasta la siguiente intersección donde sea posible. El personaje continúa por su dirección actual mientras el camino esté libre.
- Cada pastilla vale 10 puntos; cada poder vale 50 y dura 8 segundos reales. Dentro del mismo efecto, los cuatro fantasmas distintos valen 200, 400, 800 y 1600 puntos. El reloj del poder sigue avanzando durante la pausa para respetar los timestamps del contrato de GameStats.
- Los fantasmas usan búsqueda de caminos en JavaScript: Blinky persigue, Pinky anticipa, Inky alterna patrulla y persecución, Clyde se retira cuando estás cerca. Durante un poder se alejan. Un fantasma capturado permanece fuera del tablero hasta que termina ese efecto.
- **Nueva partida** finaliza la anterior con motivo `RESTARTED` y prepara otra con UUID nuevo. Pausar y continuar conservan el identificador. No hay conexión con Prolog.
- Puedes abrir varias pestañas con estados y colas independientes. Al ocultar una pestaña se pausa su juego automáticamente; varias ventanas visibles pueden jugar al mismo tiempo. No se guarda el laberinto para reanudar después de recargar.

### Organización orientada a objetos

`static/js/pacman-engine.js` contiene `Maze` (topología y pastillas), `Actor` (posición y movimiento), `Ghost` (decisiones) y `PacmanGame` (reglas, estado y ciclo de vida). No depende del DOM. `static/js/pacman.js` contiene `PacmanRenderer` y `PacmanController`, responsables de dibujo, entradas y presentación. `EventDelivery`, en `static/js/gamestats.js`, administra el envío sin bloquear el juego. Flask sirve la interfaz y funciona como puente HTTP para GameStats.

## Conectar GameStats

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

### Eventos y fallos

Se envía exactamente el sobre exigido: `eventId`, `timestamp` UTC, `gameId: PACMAN`, `gameVersion: 1.0`, `matchId`, `sequence`, `playerId`, `type`, `data`. La secuencia comienza en 1. Inicio y final llevan `playerId: null`; las acciones llevan el jugador registrado en el inicio. El jugador anónimo se conserva en `localStorage` para consultar su historial.

Se generan `MATCH_STARTED`, `PELLET_EATEN`, `POWER_UP_COLLECTED`, `GHOST_EATEN`, `LIFE_LOST`, `LEVEL_COMPLETED` y `MATCH_FINISHED`. No se envían eventos de movimiento o pausa que ese contrato rechazaría. Los poderes se referencian por el ID del evento original. Un efecto no admite dos capturas del mismo fantasma.

Cada partida tiene una cola ordenada y una sola solicitud en curso; partidas distintas pueden enviar en paralelo. Los fallos de red y errores 5xx se reintentan a los cinco segundos conservando IDs y secuencias. El `409 DUPLICATE_EVENT` confirma un reenvío ya recibido. Los errores de validación conservan el evento y detienen esa cola hasta un reintento manual; se muestran en pantalla.

Los eventos pendientes se conservan en `sessionStorage` para reintentar al recargar la misma pestaña. Si el navegador bloquea el almacenamiento, se conservan en memoria y se informa. **Cerrar definitivamente la pestaña puede perder los pendientes**; no se implementó una cola durable en el servidor. `pagehide` intenta registrar la finalización, pero un cierre forzado o corte del proceso no garantiza enviarla. Descarga el JSONL antes de cerrar si necesitas conservar el registro. El archivo de una partida aún activa es parcial: no tiene `MATCH_FINISHED` hasta finalizarla.

El botón **Descargar eventos JSONL** exporta el formato que acepta el cargador Go (`-input archivo.jsonl -serve=false`). Usa un servicio de prueba limpio si esos IDs ya fueron recibidos, ya que Go los deduplica.

### Historial real frente a estado local

La puntuación, vidas y tiempo en el tablero son estado de la partida, necesario para jugar. El bloque **Tu historial** consulta Scala cada cinco segundos; no calcula sus estadísticas localmente. Sin GameStats, puedes jugar y descargar los eventos, y la pantalla muestra el estado pendiente.

La versión consultada de GameStats persiste y analiza partidas al recibir `MATCH_FINISHED`; por eso su historial cambia al finalizar, aunque los eventos se envían mientras juegas. Esta API no ofrece estadísticas analíticas parciales de una partida en curso. Las métricas globales del resumen principal siguen siendo de demostración. La integración del panel global y las estadísticas en curso del enunciado quedan pendientes de su desarrollo y del soporte de GameStats.

## Pruebas

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

## Alcance pendiente

Carreras y ajedrez siguen como demostraciones. La integración Prolog corresponderá al juego elegido para ello, no a Pac-Man. El resumen global, deployment, Docker y demás entregables generales del proyecto no se completan con esta primera implementación.
