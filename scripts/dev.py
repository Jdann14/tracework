"""Start API, worker and Vite; stop all children together on Ctrl+C."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
if (REPO / ".env").exists():
    for line in (REPO / ".env").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
commands = [
    [sys.executable, "-m", "uvicorn", "tracework.api:app", "--host", "127.0.0.1", "--port", "8000"],
    [sys.executable, "-m", "tracework.worker"],
    ["npm", "run", "dev", "--prefix", "web"],
]
children = []


def stop(signum=None, frame=None):
    for process in children:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in children:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    for command in commands:
        children.append(subprocess.Popen(command, start_new_session=True))
    print("Tracework → http://127.0.0.1:4318", flush=True)
    while all(p.poll() is None for p in children):
        time.sleep(0.5)
    print("A service exited; stopping the remaining services.", flush=True)
finally:
    stop()
