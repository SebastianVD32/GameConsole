"""Eventos específicos de cada juego según el contrato implementado en GameStats.

Cada clase solo conoce los tipos de evento y los campos de ``data`` que acepta
el servicio Go; el sobre común lo agrega ``EventStream``. Pac-Man y Carreras
quedan listos para que sus juegos solo llamen a estos métodos.
"""

from __future__ import annotations

from typing import ClassVar, Iterable

from .stream import EventStream


class GameEvents:
    """Base común: ciclo de vida de la partida."""

    game_id: ClassVar[str]

    def __init__(self, stream: EventStream) -> None:
        if stream.game_id != self.game_id:
            raise ValueError(f"El flujo pertenece a {stream.game_id}, no a {self.game_id}")
        self._stream = stream

    @property
    def stream(self) -> EventStream:
        return self._stream

    def _started(self, data: dict) -> dict:
        return self._stream.emit("MATCH_STARTED", None, data)

    def _finished(self, data: dict) -> dict:
        return self._stream.emit("MATCH_FINISHED", None, data)

    def _action(self, event_type: str, player_id: str, data: dict) -> dict:
        if not player_id:
            raise ValueError("Las acciones deben identificar al jugador")
        return self._stream.emit(event_type, player_id, data)


class ChessEvents(GameEvents):
    game_id = "CHESS"

    def match_started(self, participants: Iterable[tuple[str, str]], initial_clock_ms: int,
                      increment_ms: int) -> dict:
        return self._started({
            "participants": [{"playerId": pid, "color": color} for pid, color in participants],
            "initialClockMs": initial_clock_ms,
            "incrementMs": increment_ms,
        })

    def ai_decision(self, player_id: str, move_number: int, origin: str, target: str, depth: int,
                    nodes: int, score: int, think_time_ms: int) -> dict:
        return self._action("AI_DECISION", player_id, {
            "moveNumber": move_number,
            "from": origin,
            "to": target,
            "depth": depth,
            "nodesEvaluated": nodes,
            "score": score,
            "thinkTimeMs": think_time_ms,
        })

    def move_played(self, player_id: str, move_number: int, piece: str, origin: str, target: str,
                    decision_ms: int, clock_before_ms: int, clock_after_ms: int) -> dict:
        return self._action("MOVE_PLAYED", player_id, {
            "moveNumber": move_number,
            "piece": piece,
            "from": origin,
            "to": target,
            "decisionTimeMs": decision_ms,
            "clockBeforeMs": clock_before_ms,
            "clockAfterMs": clock_after_ms,
        })

    def piece_captured(self, player_id: str, move_event_id: str, captured_piece: str,
                       captured_player_id: str) -> dict:
        return self._action("PIECE_CAPTURED", player_id, {
            "moveEventId": move_event_id,
            "capturedPiece": captured_piece,
            "capturedPlayerId": captured_player_id,
        })

    def match_finished(self, winner_player_id: str | None, reason: str) -> dict:
        return self._finished({"winnerPlayerId": winner_player_id, "reason": reason})


class PacmanEvents(GameEvents):
    game_id = "PACMAN"

    def match_started(self, player_id: str, initial_level: int = 1, initial_lives: int = 3) -> dict:
        return self._started({"playerId": player_id, "initialLevel": initial_level, "initialLives": initial_lives})

    def pellet_eaten(self, player_id: str, level: int, pellet_id: str) -> dict:
        return self._action("PELLET_EATEN", player_id, {"level": level, "pelletId": pellet_id})

    def power_up_collected(self, player_id: str, level: int, pellet_id: str, duration_ms: int) -> dict:
        return self._action("POWER_UP_COLLECTED", player_id,
                            {"level": level, "pelletId": pellet_id, "durationMs": duration_ms})

    def ghost_eaten(self, player_id: str, level: int, ghost_id: str, power_up_event_id: str) -> dict:
        return self._action("GHOST_EATEN", player_id,
                            {"level": level, "ghostId": ghost_id, "powerUpEventId": power_up_event_id})

    def life_lost(self, player_id: str, level: int, cause: str, lives_remaining: int) -> dict:
        return self._action("LIFE_LOST", player_id,
                            {"level": level, "cause": cause, "livesRemaining": lives_remaining})

    def level_completed(self, player_id: str, level: int) -> dict:
        return self._action("LEVEL_COMPLETED", player_id, {"level": level})

    def match_finished(self, score: int, reason: str) -> dict:
        return self._finished({"score": score, "reason": reason})


class RacingEvents(GameEvents):
    game_id = "RACING"

    def match_started(self, driver_ids: Iterable[str], planned_laps: int) -> dict:
        return self._started({"driverIds": list(driver_ids), "plannedLaps": planned_laps})

    def lap_completed(self, player_id: str, lap_number: int, lap_time_ms: int, position: int) -> dict:
        return self._action("LAP_COMPLETED", player_id,
                            {"lapNumber": lap_number, "lapTimeMs": lap_time_ms, "position": position})

    def pit_entered(self, player_id: str, stop_id: str, lap_number: int, reason: str) -> dict:
        return self._action("PIT_ENTERED", player_id,
                            {"stopId": stop_id, "lapNumber": lap_number, "reason": reason})

    def pit_exited(self, player_id: str, stop_id: str, lap_number: int, tire_compound: str) -> dict:
        return self._action("PIT_EXITED", player_id,
                            {"stopId": stop_id, "lapNumber": lap_number, "tireCompound": tire_compound})

    def penalty_applied(self, player_id: str, penalty_type: str, value: int, reason: str,
                        lap_number: int) -> dict:
        return self._action("PENALTY_APPLIED", player_id, {
            "penaltyType": penalty_type, "value": value, "reason": reason, "lapNumber": lap_number,
        })

    def match_finished(self, classification: Iterable[tuple[str, int]]) -> dict:
        return self._finished({
            "classification": [{"playerId": pid, "position": pos} for pid, pos in classification],
        })

    def match_aborted(self, reason: str) -> dict:
        if reason not in ("USER_QUIT", "RESTARTED", "PAGE_CLOSED"):
            raise ValueError("Motivo de abandono inválido")
        return self.stream.emit("MATCH_ABORTED", None, {"reason": reason})
