# GameConsole

Base visual en Python/Flask para una consola web con tres juegos, partidas simultáneas y un panel preparado para consumir estadísticas de GameStats.

## Ejecutar localmente

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Abre `http://127.0.0.1:5000`.

## Estado actual

- Diseño adaptable para escritorio, tableta y móvil.
- Resumen principal con biblioteca, actividad y métricas.
- Vista compartida para Ajedrez, Pac-Man y Juego de carreras.
- Datos e interacciones de demostración; todavía no existe lógica de juego.
- Estructura lista para añadir modelos orientados a objetos, integración Prolog y consumo de GameStats.
