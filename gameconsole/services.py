"""Composición de dependencias de la consola."""

from __future__ import annotations

import os
import random
import re
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field

from .events import ChessEvents, EventDispatcher, EventSink, EventStream, HttpEventTransport, MemorySink
from .games.chess import ChessMatch, Color, ComputerPlayer, HumanPlayer, TimeControl
from .games.chess.ai import ChessEngine, PrologChessEngine
from .registry import MatchRegistry
from .stats import GameStatsQuery

TIME_CONTROLS = {
    "3+2": TimeControl(3 * 60_000, 2_000),
    "5+3": TimeControl(5 * 60_000, 3_000),
    "10+5": TimeControl(10 * 60_000, 5_000),
}
DIFFICULTIES = {1: "Principiante", 2: "Intermedio", 3: "Avanzado", 4: "Experto"}


@dataclass
class Settings:
    ingest_url: str = ""
    analytics_url: str = ""
    ai_workers: int = 4
    send_workers: int = 8

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ingest_url=os.environ.get("GAMESTATS_INGEST_URL", "http://localhost:8080"),
            analytics_url=os.environ.get("GAMESTATS_ANALYTICS_URL", "http://localhost:8081"),
            ai_workers=int(os.environ.get("GAMECONSOLE_AI_WORKERS", "4")),
            send_workers=int(os.environ.get("GAMECONSOLE_SEND_WORKERS", "8")),
        )


def player_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:32] or "jugador"


@dataclass
class ConsoleServices:
    registry: MatchRegistry
    sink: EventSink
    engine: ChessEngine
    ai_executor: Executor
    stats: GameStatsQuery
    dispatcher: EventDispatcher | None = None
    rng: random.Random = field(default_factory=random.Random)

    @classmethod
    def build(cls, settings: Settings) -> "ConsoleServices":
        dispatcher = None
        sink: EventSink
        if settings.ingest_url:
            dispatcher = EventDispatcher(HttpEventTransport(settings.ingest_url), max_workers=settings.send_workers)
            sink = dispatcher
        else:
            sink = MemorySink()
        registry = MatchRegistry()
        registry.start_ticker()
        return cls(
            registry=registry,
            sink=sink,
            engine=PrologChessEngine(),
            ai_executor=ThreadPoolExecutor(max_workers=settings.ai_workers, thread_name_prefix="prolog-ai"),
            stats=GameStatsQuery(settings.ingest_url, settings.analytics_url),
            dispatcher=dispatcher,
        )

    def new_chess_match(self, name: str, color: str, depth: int, control: str) -> ChessMatch:
        if depth not in DIFFICULTIES:
            raise ValueError("Dificultad inválida")
        if control not in TIME_CONTROLS:
            raise ValueError("Control de tiempo inválido")
        if color == "RANDOM":
            color = self.rng.choice(["WHITE", "BLACK"])
        try:
            human_color = Color(color)
        except ValueError as error:
            raise ValueError("Color inválido") from error

        match_id = f"chess-{uuid.uuid4()}"
        display = name.strip()[:32] or "Jugador"
        human = HumanPlayer(f"jugador-{player_slug(display)}", display, human_color)
        computer = ComputerPlayer(f"ia-prolog-n{depth}", f"IA Prolog · {DIFFICULTIES[depth]}",
                                  human_color.opponent, self.engine, depth)
        stream = EventStream("CHESS", ChessMatch.game_version, match_id, self.sink)
        match = ChessMatch(match_id, human, computer, TIME_CONTROLS[control], ChessEvents(stream), self.ai_executor)
        self.registry.add(match)
        match.start()
        return match

    def delivery(self, match_id: str) -> dict | None:
        if self.dispatcher is None:
            return {"state": "DISABLED", "pending": 0, "delivered": 0, "lastError": "GameStats no configurado"}
        return self.dispatcher.status(match_id)
