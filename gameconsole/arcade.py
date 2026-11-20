"""Durable arcade event relay. Stores exact events; GameStats still computes statistics."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from .events.dispatcher import HttpEventTransport, TransportError


class EventConflict(ValueError):
    pass


class ArcadeRelay:
    TYPES = {
        "PACMAN": {"MATCH_STARTED", "MATCH_FINISHED", "PELLET_EATEN", "POWER_UP_COLLECTED", "GHOST_EATEN", "LIFE_LOST", "LEVEL_COMPLETED"},
        "RACING": {"MATCH_STARTED", "MATCH_FINISHED", "MATCH_ABORTED", "LAP_COMPLETED", "PIT_ENTERED", "PIT_EXITED", "PENALTY_APPLIED"},
    }
    FIELDS = {"eventId", "timestamp", "gameId", "gameVersion", "matchId", "sequence", "playerId", "type", "data"}

    def __init__(self, path: str, transport=None, workers: int = 4, auto_start: bool = True):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS arcade_matches (
              match_id TEXT PRIMARY KEY, game_id TEXT NOT NULL, version TEXT NOT NULL,
              created_at TEXT NOT NULL, last_seq INTEGER NOT NULL DEFAULT 0,
              next_seq INTEGER NOT NULL DEFAULT 1, finished INTEGER NOT NULL DEFAULT 0,
              delivery_state TEXT NOT NULL DEFAULT 'PENDING', error TEXT,
              retry_at REAL NOT NULL DEFAULT 0, resyncs INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS arcade_events (
              event_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, sequence INTEGER NOT NULL,
              payload TEXT NOT NULL, UNIQUE(match_id, sequence));
        """)
        self._transport = transport
        self._lock = threading.RLock()
        self._busy: set[str] = set()
        self._stop = threading.Event()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="arcade-delivery")
        self._thread = None
        if auto_start:
            self._thread = threading.Thread(target=self._loop, name="arcade-relay", daemon=True)
            self._thread.start()

    @classmethod
    def build(cls, path: str, ingest_url: str):
        return cls(path, HttpEventTransport(ingest_url, timeout=4))

    @classmethod
    def validate(cls, event):
        if not isinstance(event, dict) or set(event) != cls.FIELDS:
            raise ValueError("El evento debe contener exactamente los campos del sobre GameStats.")
        for field in ("eventId", "gameId", "gameVersion", "matchId", "timestamp", "type"):
            if not isinstance(event[field], str) or not event[field].strip():
                raise ValueError(f"{field} debe ser texto no vacío.")
        if event["gameId"] not in cls.TYPES or event["type"] not in cls.TYPES[event["gameId"]]:
            raise ValueError("Juego o tipo de evento arcade no admitido.")
        if type(event["sequence"]) is not int or event["sequence"] < 1 or not isinstance(event["data"], dict):
            raise ValueError("Secuencia o datos de evento inválidos.")
        moment = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        if moment.utcoffset() != timedelta(0):
            raise ValueError("El timestamp debe estar expresado en UTC.")
        if event["type"] in ("MATCH_STARTED", "MATCH_FINISHED", "MATCH_ABORTED"):
            if event["playerId"] is not None:
                raise ValueError("Los eventos de ciclo de vida llevan playerId null.")
        elif not isinstance(event["playerId"], str) or not event["playerId"].strip():
            raise ValueError("Las acciones identifican a su jugador.")

    def append(self, event):
        self.append_batch([event])
        return {"accepted": True, "persisted": True, "eventId": event["eventId"],
                "matchId": event["matchId"], "delivery": self.status(event["matchId"])}

    def append_batch(self, events):
        if not isinstance(events, list) or not 1 <= len(events) <= 1000:
            raise ValueError("El lote debe contener entre 1 y 1000 eventos.")
        for event in events:
            self.validate(event)
        # Commit the entire batch or none of it, including duplicate-ID checks.
        with self._lock, self._db:
            for event in events:
                self._append(event)

    def _append(self, event):
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        old = self._db.execute("SELECT payload FROM arcade_events WHERE event_id=?", (event["eventId"],)).fetchone()
        if old:
            if old[0] != encoded:
                raise EventConflict("eventId ya existe con contenido diferente.")
            return
        match_id = event["matchId"]
        row = self._db.execute("SELECT * FROM arcade_matches WHERE match_id=?", (match_id,)).fetchone()
        if row is None:
            if event["sequence"] != 1 or event["type"] != "MATCH_STARTED":
                raise ValueError("La partida debe comenzar con MATCH_STARTED y sequence 1.")
            self._db.execute("INSERT INTO arcade_matches(match_id,game_id,version,created_at) VALUES(?,?,?,?)",
                             (match_id, event["gameId"], event["gameVersion"], event["timestamp"]))
        else:
            if row["game_id"] != event["gameId"] or row["version"] != event["gameVersion"]:
                raise EventConflict("La identidad de la partida no puede cambiar.")
            if row["finished"] or event["type"] == "MATCH_STARTED" or event["sequence"] != row["last_seq"] + 1:
                raise EventConflict("Secuencia fuera de orden o partida ya finalizada.")
            previous = json.loads(self._db.execute("SELECT payload FROM arcade_events WHERE match_id=? AND sequence=?",
                                                  (match_id, row["last_seq"])).fetchone()[0])
            if datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")) < datetime.fromisoformat(previous["timestamp"].replace("Z", "+00:00")):
                raise ValueError("Los timestamps de la partida no pueden retroceder.")
        self._db.execute("INSERT INTO arcade_events VALUES(?,?,?,?)", (event["eventId"], match_id, event["sequence"], encoded))
        self._db.execute("UPDATE arcade_matches SET last_seq=?,finished=?,delivery_state=CASE WHEN delivery_state='DELIVERED' THEN 'PENDING' ELSE delivery_state END WHERE match_id=?",
                         (event["sequence"], int(event["type"] in ("MATCH_FINISHED", "MATCH_ABORTED")), match_id))

    def status(self, match_id):
        with self._lock:
            row = self._db.execute("SELECT * FROM arcade_matches WHERE match_id=?", (match_id,)).fetchone()
            if not row:
                return None
            return {"matchId": match_id, "gameId": row["game_id"], "state": row["delivery_state"],
                    "pending": max(0, row["last_seq"] - row["next_seq"] + 1),
                    "delivered": min(row["last_seq"], row["next_seq"] - 1),
                    "lastError": row["error"], "resyncs": row["resyncs"]}

    def summaries(self):
        with self._lock:
            rows = self._db.execute("""SELECT m.*, e.payload AS last_payload FROM arcade_matches m
                JOIN arcade_events e ON e.match_id=m.match_id AND e.sequence=m.last_seq
                ORDER BY m.created_at DESC""").fetchall()
            return [{"matchId": r["match_id"], "gameId": r["game_id"],
                     "slug": "pacman" if r["game_id"] == "PACMAN" else "carreras",
                     "finished": bool(r["finished"]), "status": "Abortada" if json.loads(r["last_payload"])["type"] == "MATCH_ABORTED" else "Finalizada" if r["finished"] else "Instancia arcade iniciada",
                     "createdAt": r["created_at"], "arcade": True} for r in rows]

    def history(self, match_id):
        with self._lock:
            return [json.loads(r[0]) for r in self._db.execute("SELECT payload FROM arcade_events WHERE match_id=? ORDER BY sequence", (match_id,))]

    def retry(self, match_id):
        with self._lock, self._db:
            self._db.execute("UPDATE arcade_matches SET delivery_state='PENDING',error=NULL,retry_at=0,resyncs=0 WHERE match_id=?", (match_id,))

    def drain(self, match_id):
        """Serial within a match. Independent matches use independent pool jobs."""
        while not self._stop.is_set():
            with self._lock:
                row = self._db.execute("SELECT * FROM arcade_matches WHERE match_id=?", (match_id,)).fetchone()
                if not row or row["delivery_state"] == "REJECTED" or row["retry_at"] > time.time():
                    return
                stored = self._db.execute("SELECT payload FROM arcade_events WHERE match_id=? AND sequence=?", (match_id, row["next_seq"])).fetchone()
                if not stored:
                    return
                event = json.loads(stored[0])
            try:
                if self._transport is None:
                    raise TransportError("GameStats no está configurado")
                response = self._transport.post_event(event)
                duplicate = response.status == 409 and (response.body or {}).get("code") == "DUPLICATE_EVENT"
                accepted = response.status in (200, 201) and (response.body or {}).get("accepted") is True
                message = str((response.body or {}).get("message", f"HTTP {response.status}"))
                forgotten = response.status == 422 and "MATCH_STARTED" in message and event["sequence"] > 1
                with self._lock, self._db:
                    if accepted or duplicate:
                        cursor = event["sequence"] + 1
                        self._db.execute("UPDATE arcade_matches SET next_seq=?,delivery_state=CASE WHEN last_seq<? THEN 'DELIVERED' ELSE 'PENDING' END,error=NULL,retry_at=0 WHERE match_id=?",
                                         (cursor, cursor, match_id))
                    elif forgotten and row["resyncs"] < 5:
                        self._db.execute("UPDATE arcade_matches SET next_seq=1,resyncs=resyncs+1,error=NULL,retry_at=0 WHERE match_id=?", (match_id,))
                    elif response.status >= 500 or response.status == 429:
                        self._failure(match_id, message)
                        return
                    else:
                        self._db.execute("UPDATE arcade_matches SET delivery_state='REJECTED',error=? WHERE match_id=?", (message, match_id))
                        return
            except (TransportError, OSError, ValueError) as error:
                with self._lock, self._db:
                    self._failure(match_id, str(error))
                return

    def _failure(self, match_id, message):
        self._db.execute("UPDATE arcade_matches SET delivery_state='RETRYING',error=?,retry_at=? WHERE match_id=?", (message, time.time() + 5, match_id))

    def _run(self, match_id):
        try:
            self.drain(match_id)
        finally:
            with self._lock:
                self._busy.discard(match_id)

    def _loop(self):
        while not self._stop.wait(0.2):
            with self._lock:
                rows = self._db.execute("SELECT match_id FROM arcade_matches WHERE next_seq<=last_seq AND retry_at<=? AND delivery_state!='REJECTED'", (time.time(),)).fetchall()
                for row in rows:
                    if row[0] not in self._busy:
                        self._busy.add(row[0])
                        try:
                            self._executor.submit(self._run, row[0])
                        except RuntimeError:
                            self._busy.discard(row[0])
                            return

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            self._db.close()
