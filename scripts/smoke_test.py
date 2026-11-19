"""Prueba de humo de la ejecución integrada (consola + Prolog + GameStats).

Inicia varias partidas de ajedrez en paralelo contra la IA Prolog, juega
movimientos legales, termina las partidas y verifica que GameStats (Go y Scala)
las haya registrado. Uso:

    python scripts/smoke_test.py [http://127.0.0.1:5000] [--matches 3] [--moves 6]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def call(base: str, path: str, body: dict | None = None, method: str | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, method=method or ("POST" if body is not None else "GET"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def wait_for(predicate, timeout: float, message: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.5)
    raise AssertionError(message)


def play_match(base: str, index: int, moves: int) -> str:
    status, state = call(base, "/api/ajedrez/partidas", {
        "name": f"Smoke {index}", "color": "WHITE" if index % 2 == 0 else "BLACK", "depth": 1, "control": "3+2",
    })
    assert status == 201, state
    match_id = state["matchId"]
    rng = random.Random(index)
    played = 0
    def ready():
        current = call(base, f"/api/ajedrez/partidas/{match_id}")[1]
        return current if current["legalMoves"] or current["finished"] else None

    while played < moves and not state["finished"]:
        state = wait_for(ready, 30, f"{match_id}: la IA no respondió")
        if state["finished"]:
            break
        move = rng.choice(state["legalMoves"])
        uci = move["from"] + move["to"] + (move["promotion"] or "")
        status, state = call(base, f"/api/ajedrez/partidas/{match_id}/movimientos", {"move": uci})
        assert status == 200, state
        played += 1
    if not state["finished"]:
        status, state = call(base, f"/api/ajedrez/partidas/{match_id}/abandonar", {})
        assert status == 200, state
    ai_decisions = sum(1 for move in state["history"] if move["byComputer"])
    print(f"  {match_id}: {len(state['history'])} jugadas ({ai_decisions} de la IA Prolog) · {state['result']['detail']}")
    return match_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:5000")
    parser.add_argument("--matches", type=int, default=3)
    parser.add_argument("--moves", type=int, default=6)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    wait_for(lambda: call(base, "/healthz")[0] == 200, 60, "La consola no respondió")
    _, before = call(base, "/api/estadisticas")
    assert not before["errors"], before["errors"]
    analyzed_before = before["analytics"]["games"]["CHESS"]["completedMatches"]
    print(f"GameStats conectado. Partidas de ajedrez analizadas antes: {analyzed_before}")

    print(f"Jugando {args.matches} partidas en paralelo…")
    with ThreadPoolExecutor(max_workers=args.matches) as pool:
        match_ids = list(pool.map(lambda i: play_match(base, i, args.moves), range(args.matches)))
    assert len(set(match_ids)) == args.matches, "Los matchId deben ser únicos"

    for match_id in match_ids:
        wait_for(lambda: (call(base, f"/api/ajedrez/partidas/{match_id}")[1]["delivery"] or {}).get("pending") == 0,
                 30, f"{match_id}: quedaron eventos sin entregar")
        state = call(base, f"/api/ajedrez/partidas/{match_id}")[1]
        assert state["delivery"]["state"] == "OK", state["delivery"]
        status, result = call(base, f"/api/estadisticas/partidas/{match_id}")
        assert status == 200, f"Scala no tiene resultado de {match_id}: {result}"
        assert result["totalMoves"] == len(state["history"]), (result["totalMoves"], len(state["history"]))

    stats = wait_for(lambda: (s := call(base, "/api/estadisticas")[1])["analytics"]["games"]["CHESS"]["completedMatches"]
                     >= analyzed_before + args.matches and s, 30, "Las estadísticas no se actualizaron")
    chess = stats["analytics"]["games"]["CHESS"]
    instances = next(g for g in stats["ingestion"]["games"] if g["gameId"] == "CHESS")
    print(f"GameStats · instancias de ajedrez iniciadas: {instances['startedMatches']}, finalizadas: {instances['finishedMatches']}")
    print(f"GameStats · partidas analizadas: {chess['completedMatches']}, decisiones IA registradas: {chess['ai']['decisions']}")
    assert chess["ai"]["decisions"] > 0, "No se registraron decisiones de la IA"
    print("Prueba de humo superada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
