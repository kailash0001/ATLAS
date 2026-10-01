"""Start or stop the workspace-owned control API and production Next.js console."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import psutil
from native_observability import owned_process, wait_healthy

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
STATE = LOCAL / "console-processes.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down"])
    args = parser.parse_args()
    LOCAL.mkdir(exist_ok=True)
    saved = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if args.action == "down":
        for name in list(reversed(saved)):
            process = owned_process(saved[name])
            if process:
                children = process.children(recursive=True)
                for child in reversed(children):
                    child.terminate()
                process.terminate()
                _, alive = psutil.wait_procs([process, *children], timeout=10)
                if alive:
                    raise RuntimeError("Owned service did not stop; keeping its saved identity")
            del saved[name]
            STATE.write_text(json.dumps(saved), encoding="utf-8")
        return
    token = LOCAL / "control-token"
    if not token.exists():
        token.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    env = {
        **os.environ,
        "AEGIS_CONTROL_TOKEN": token.read_text(encoding="utf-8"),
        "NEXT_TELEMETRY_DISABLED": "1",
        "MLFLOW_DISABLE_AGENT_HINT": "1",
    }
    node = shutil.which("node")
    if not node or not (ROOT / "apps/console/.next/BUILD_ID").exists():
        raise SystemExit("Install Node.js and run npm ci && npm run build in apps/console first")
    commands = {
        "control-api": (
            [
                sys.executable,
                "-m",
                "uvicorn",
                "apps.control_api.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8100",
            ],
            "http://127.0.0.1:8100/health/ready",
        ),
        "console": (
            [
                node,
                str(ROOT / "apps/console/node_modules/next/dist/bin/next"),
                "start",
                str(ROOT / "apps/console"),
                "--hostname",
                "127.0.0.1",
                "--port",
                "3100",
            ],
            "http://127.0.0.1:3100",
        ),
    }
    for name, (command, url) in commands.items():
        if name in saved and owned_process(saved[name]):
            print(f"{name} already running: {url}")
            continue
        with (LOCAL / f"{name}.log").open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        saved[name] = {
            "pid": process.pid,
            "created_at": psutil.Process(process.pid).create_time(),
            "command": command,
        }
        STATE.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        wait_healthy(url, process)
        print(f"{name} ready: {url}", flush=True)


if __name__ == "__main__":
    main()
