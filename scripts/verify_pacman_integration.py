"""Run isolated Flask + real GameStats Go, then send two concurrent match scenarios.

Usage: .venv/Scripts/python scripts/verify_pacman_integration.py ../GameStats
Requires Node 22+, Go 1.24+ and the GameStats source checkout. Does not require Docker.
"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main(test_file="tests/gamestats.integration.cjs", game_path="/juegos/pacman"):
    root = Path(__file__).resolve().parents[1]
    source = Path(sys.argv[1]).resolve() / "go-ingestion"
    if not (source / "go.mod").is_file():
        raise SystemExit("Indica la ruta del repositorio GameStats como primer argumento.")
    ingestion_port, console_port = free_port(), free_port()
    while ingestion_port == console_port:
        console_port = free_port()
    env = dict(os.environ, GAMESTATS_INGESTION_URL=f"http://127.0.0.1:{ingestion_port}",
               GAMESTATS_INGEST_URL=f"http://127.0.0.1:{ingestion_port}",
               CONSOLE_URL=f"http://127.0.0.1:{console_port}")
    processes = []
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with tempfile.TemporaryDirectory(prefix="gameconsole-integration-") as tmp:
        with open(Path(tmp) / "services.log", "w+", encoding="utf-8") as log:
            try:
                binary = Path(tmp) / ("gamestats.exe" if os.name == "nt" else "gamestats")
                subprocess.run([shutil.which("go"), "build", "-o", str(binary), "./cmd/gamestats"],
                               cwd=source, env=env, check=True, **flags)
                commands = [
                    [str(binary), "-address", f"127.0.0.1:{ingestion_port}", "-output", str(Path(tmp) / "matches.jsonl")],
                    [sys.executable, "-m", "flask", "--app", "app", "run", "--port", str(console_port)],
                ]
                for cmd in commands:
                    processes.append(subprocess.Popen(cmd, cwd=root, env=env, stdout=log, stderr=log, **flags))
                for url in [env["GAMESTATS_INGESTION_URL"] + "/healthz", env["CONSOLE_URL"] + game_path]:
                    deadline = time.monotonic() + 30
                    while True:
                        try:
                            with urlopen(url, timeout=1) as response:
                                if response.status == 200:
                                    break
                        except (URLError, TimeoutError):
                            pass
                        if any(p.poll() is not None for p in processes) or time.monotonic() > deadline:
                            raise RuntimeError(f"No se pudo iniciar {url}")
                        time.sleep(0.2)
                result = subprocess.run([shutil.which("node"), test_file], cwd=root, env=env,
                                        capture_output=True, text=True, encoding="utf-8", **flags)
                print(result.stdout)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                result.check_returncode()
            except Exception:
                log.flush()
                log.seek(0)
                print("\n".join(log.read().splitlines()[-25:]), file=sys.stderr)
                raise
            finally:
                for process in processes:
                    process.terminate()
                for process in processes:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
