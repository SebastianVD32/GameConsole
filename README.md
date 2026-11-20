# GameConsole

Consola web de videojuegos desarrollada para el curso de **Lenguajes de Programación**. Integra tres juegos orientados a objetos, un oponente inteligente implementado en Prolog, ejecución concurrente de partidas y estadísticas en tiempo real proporcionadas por [GameStats](https://github.com/SebastianVD32/GameStats).

## Acceso y demostración

- [Abrir GameConsole](https://gameconsole-nkx6wjmnfl4di.eastus.cloudapp.azure.com): acceso desde el navegador, sin instalar componentes.
- [Ver el video demostrativo](https://drive.google.com/file/d/17kTfgxgQDRCX1NYrtCkBt1XXv0sd_4mm/view?usp=sharing).
- [Guía de instalación y despliegue](deploy/README.md).

## Juegos

| Juego | Modalidad | Implementación destacada |
|---|---|---|
| **Ajedrez** | Jugador contra computadora | Reglas y estado en Python; IA en SWI-Prolog mediante negamax, poda alfa-beta y búsqueda de quiescencia. |
| **Pac-Man** | Arcade individual | Laberinto, fantasmas con estrategias distintas, poderes, puntuación y tres vidas. |
| **Carreras** | Jugador contra tres rivales | Circuito de tres vueltas, física, rivales autónomos, colisiones y clasificación. |

Cada partida recibe un `matchId` único. Esto permite ejecutar varias instancias simultáneas en pestañas distintas sin mezclar estados ni eventos.

## Cumplimiento del enunciado

| Requisito | Solución implementada |
|---|---|
| Tres juegos funcionales | Ajedrez, Pac-Man y carreras, accesibles desde la consola web. |
| Programación orientada a objetos | Clases separadas para reglas, entidades, estado, control, renderizado y ciclo de vida. |
| Usuario contra computadora con Prolog | El ajedrez consulta a SWI-Prolog para elegir cada movimiento de la IA. |
| Partidas concurrentes | Identificadores independientes, pestañas simultáneas y procesamiento por partida. |
| Eventos compatibles con GameStats | Eventos de inicio, progreso y cierre con IDs, secuencias y marcas de tiempo estables. |
| Envío sin bloquear los juegos | Colas por `matchId`, trabajadores concurrentes, persistencia y reintentos. |
| Panel de estadísticas | Consulta directamente a los servicios Go y Scala de GameStats; no recalcula sus métricas. |
| Ejecución reproducible | Docker, Docker Compose, pruebas automatizadas, CI/CD y configuración de despliegue. |

## Arquitectura

```text
Navegador
├─ Ajedrez ──────────────────────────┐
├─ Pac-Man                                      │ HTTP / JSON
└─ Carreras                                     │
                                                ▼
                                  GameConsole (Flask)
                                  ├─ Registro de partidas
                                  ├─ Motor de eventos
                                  ├─ Cola arcade en SQLite
                                  └─ Puente Python ↔ SWI-Prolog
                                                │
                    ┌─────────────────────────────────────────────┐
                    ▼                                             ▼
          GameStats Go (ingestión)                    GameStats Scala (análisis)
          valida y agrupa eventos                       calcula estadísticas
```

### Componentes principales

- `gameconsole/games/chess/`: modelo orientado a objetos, reglas, reloj y ciclo de vida del ajedrez.
- `gameconsole/games/chess/ai/chess_ai.pl`: generación y evaluación de jugadas en Prolog.
- `static/js/pacman-engine.js` y `static/js/racing-engine.js`: reglas arcade independientes del DOM.
- `gameconsole/events/`: contratos, secuencias y entrega concurrente de eventos de ajedrez.
- `gameconsole/arcade.py`: diario SQLite y reenvío confiable de eventos arcade.
- `templates/` y `static/`: interfaz, controles, renderizado y panel de estadísticas.

## Integración con GameStats

Los tres juegos producen eventos con el sobre requerido por GameStats:

```text
eventId · timestamp · gameId · gameVersion · matchId
sequence · playerId · type · data
```

- La secuencia comienza en `1` y se mantiene ordenada dentro de cada partida.
- Ajedrez emite, entre otros, `MATCH_STARTED`, `AI_DECISION`, `MOVE_PLAYED` y `MATCH_FINISHED`.
- Pac-Man registra pastillas, poderes, fantasmas, vidas, niveles y resultado final.
- Carreras registra vueltas, finalización y abandonos.
- Los fallos de red no detienen el juego: los eventos pendientes se conservan y se reintentan.
- El panel `/estadisticas` consulta periódicamente a GameStats y separa métricas generales, por juego y partidas en curso. Cada juego incluye además un resumen actualizado cada 2,5 segundos; los resultados finales aparecen después de procesar el cierre.

## Ejecución con Docker

Esta es la forma recomendada porque incluye Flask, SWI-Prolog y los dos servicios de GameStats.

### Requisitos

- Docker con Compose.
- Este repositorio y GameStats en carpetas contiguas:

```text
Lenguages/
├─ GameConsole/
└─ GameStats/
```

Clona GameStats si todavía no está disponible:

```powershell
git clone https://github.com/SebastianVD32/GameStats.git ..\GameStats
```

La revisión compatible usada por CI se encuentra en `GAMESTATS_REF` dentro de `.github/workflows/ci.yml`. El checkout local de GameStats debe incluir los contratos de ajedrez, Pac-Man, carreras y `MATCH_ABORTED`.

Inicia el sistema completo:

```powershell
docker compose up --build --wait -d
```

Servicios disponibles:

- GameConsole: <http://localhost:5000>
- GameStats Go: <http://localhost:8080/healthz>
- GameStats Scala: <http://localhost:8081/healthz>

Si GameStats se encuentra en otra ruta:

```powershell
$env:GAMESTATS_DIR = 'C:\ruta\GameStats'
docker compose up --build --wait -d
```

Para detener los servicios:

```powershell
docker compose down
```

Usa `docker compose down --volumes` solamente cuando también quieras eliminar los datos persistidos.

## Desarrollo local

### Requisitos

- Python 3.12 o posterior.
- SWI-Prolog 9.x disponible en `PATH`.
- Node.js 22 o posterior para las pruebas de los motores arcade.
- GameStats ejecutándose en los puertos configurados.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:GAMESTATS_INGEST_URL = 'http://localhost:8080'
$env:GAMESTATS_ANALYTICS_URL = 'http://localhost:8081'

python app.py
```

Variables principales:

| Variable | Valor predeterminado | Propósito |
|---|---|---|
| `GAMESTATS_INGEST_URL` | `http://localhost:8080` | Servicio Go de ingestión y resumen. |
| `GAMESTATS_ANALYTICS_URL` | `http://localhost:8081` | Servicio Scala de estadísticas. |
| `GAMECONSOLE_AI_WORKERS` | `4` | Trabajadores para decisiones Prolog. |
| `GAMECONSOLE_SEND_WORKERS` | `8` | Trabajadores para eventos de ajedrez. |
| `GAMECONSOLE_ARCADE_DB` | `data/arcade.sqlite3` | Diario persistente de eventos arcade. |

## Pruebas

Pruebas Python, incluidas reglas de ajedrez, Prolog, API, eventos y persistencia:

```powershell
python -m unittest discover -s tests -t . -v
```

Pruebas de los motores y entrega desde el navegador:

```powershell
node --test tests/*.test.cjs
```

Prueba de humo contra el sistema integrado:

```powershell
python scripts/smoke_test.py http://127.0.0.1:5000 --matches 4 --moves 6
```

Las verificaciones especializadas se encuentran en:

- `scripts/verify_pacman_integration.py`
- `scripts/verify_racing_integration.py`
- `tests/gamestats.integration.cjs`

## CI/CD y despliegue

El workflow `.github/workflows/ci.yml` ejecuta:

1. Pruebas Python dentro de una imagen con SWI-Prolog.
2. Pruebas JavaScript con Node.js 22.
3. Integración real con GameStats Go y Scala.
4. Construcción y verificación de una entrega con tres imágenes: GameConsole,
   GameStats Go y GameStats Scala, con una misma etiqueta de versión.
5. Publicación en GHCR al actualizar `main` (o ejecutar manualmente el workflow en `main`).
6. Actualización automática de Azure mediante `.github/workflows/deploy-azure.yml`
   cuando CI/CD termina correctamente en `main`. Comprueba el arranque e intenta
   recuperar la versión anterior si falla.

La instalación de producción utiliza Ubuntu en Azure East US, una VM
`Standard_F1as_v7` de 1 CPU y 4 GB de RAM, un disco SSD de 32 GB y Caddy para HTTPS.
GitHub se autentica con OIDC mediante una identidad limitada a la VM. El servidor
recibe las imágenes en un paquete temporal, sin guardar credenciales de GitHub.
Las actualizaciones reinician servicios y pueden interrumpir partidas abiertas.

Para que cualquier persona pueda jugar desde un enlace sin instalar nada, se
necesita alojamiento para los tres servicios. La configuración de Azure for Students y la
alternativa con servidor Docker están en [la guía de despliegue](deploy/README.md).
Solo la consola se expone a Internet; GameStats permanece en la red privada.

El despliegue usa imágenes publicadas, sin requerir el código fuente:

```powershell
docker compose -f deploy/compose.yaml up -d --wait
```

Selecciona la misma versión de los tres componentes mediante
`GAMECONSOLE_TAG=sha-<commit completo>`; el valor predeterminado es `latest`.
Los paquetes privados requieren autenticación del servidor con permisos de lectura.
Esto no requiere que los visitantes tengan cuenta GitHub.

## Decisiones técnicas esenciales

- **IA explicable:** Prolog recibe una posición FEN y devuelve movimiento, evaluación y nodos explorados; no elige movimientos al azar.
- **Aislamiento:** cada partida conserva su estado, identificador y secuencia de eventos.
- **Concurrencia ordenada:** los eventos de una misma partida mantienen orden FIFO, mientras partidas distintas avanzan en paralelo.
- **Persistencia arcade:** Pac-Man y carreras guardan eventos en SQLite antes de confirmarlos al navegador.
- **Separación de responsabilidades:** GameConsole ejecuta juegos y presenta datos; GameStats valida eventos y calcula estadísticas.
- **Actualización en tiempo real:** el panel usa consultas periódicas, sin duplicar cálculos de GameStats.

## Demostración

[Ver el video demostrativo en Google Drive](https://drive.google.com/file/d/17kTfgxgQDRCX1NYrtCkBt1XXv0sd_4mm/view?usp=sharing).

La demostración del proyecto comprende los tres juegos, partidas concurrentes,
la inteligencia en Prolog y la integración con el panel de GameStats.
