"""Start/stop workspace-owned inference, Prometheus and Grafana processes on Windows."""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
STATE = LOCAL / "observability.json"


def binary(name):
    marker = LOCAL / "tools" / name / "installed.json"
    if not marker.exists():
        raise RuntimeError("Run python scripts/install_monitoring.py first")
    return Path(json.loads(marker.read_text())["executable"])


def wait_healthy(url, process):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Process exited while starting {url}; inspect .local logs")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"Health check timed out: {url}; inspect .local logs")


def owned_process(record):
    try:
        process = psutil.Process(record["pid"])
        if (
            abs(process.create_time() - record["created_at"]) > 0.01
            or Path(process.cwd()).resolve() != ROOT
            or process.cmdline() != record["command"]
        ):
            raise RuntimeError("Saved PID does not identify this workspace's service")
        return process
    except psutil.NoSuchProcess:
        return None


def up():
    LOCAL.mkdir(exist_ok=True)
    for directory in ("grafana-data", "grafana-logs", "grafana-plugins", "prometheus-data"):
        (LOCAL / directory).mkdir(exist_ok=True)
    saved = json.loads(STATE.read_text()) if STATE.exists() else {}
    grafana = binary("grafana")
    grafana_home = grafana.parent.parent
    config = ROOT / "infrastructure"
    env = {
        **os.environ,
        "MLFLOW_DISABLE_AGENT_HINT": "1",
        "MLFLOW_ENABLE_TELEMETRY": "false",
        "GF_PATHS_DATA": str(LOCAL / "grafana-data"),
        "GF_PATHS_LOGS": str(LOCAL / "grafana-logs"),
        "GF_PATHS_PLUGINS": str(LOCAL / "grafana-plugins"),
        "GF_PATHS_PROVISIONING": str(config / "grafana/provisioning"),
        "GF_SERVER_HTTP_ADDR": "127.0.0.1",
        "GF_SERVER_HTTP_PORT": "3000",
        "GF_SECURITY_ADMIN_USER": "aegis",
        "GF_SECURITY_ADMIN_PASSWORD": "aegis_local",
        "GF_USERS_ALLOW_SIGN_UP": "false",
        "GF_ANALYTICS_REPORTING_ENABLED": "false",
        "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
        "GF_PLUGINS_PREINSTALL_DISABLED": "true",
        "AEGIS_PROMETHEUS_URL": "http://127.0.0.1:9090",
        "AEGIS_DASHBOARD_PATH": str(config / "grafana/dashboards"),
    }
    commands = {
        "inference": (
            [
                sys.executable,
                "-m",
                "uvicorn",
                "apps.inference.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--workers",
                "1",
                "--no-access-log",
                "--timeout-keep-alive",
                "5",
                "--limit-concurrency",
                "64",
            ],
            "http://127.0.0.1:8000/health/ready",
        ),
        "prometheus": (
            [
                str(binary("prometheus")),
                f"--config.file={config / 'prometheus/prometheus-native.yml'}",
                f"--storage.tsdb.path={LOCAL / 'prometheus-data'}",
                "--storage.tsdb.retention.time=7d",
                "--web.listen-address=127.0.0.1:9090",
            ],
            "http://127.0.0.1:9090/-/ready",
        ),
        "grafana": (
            [str(grafana), "server", "--homepath", str(grafana_home)],
            "http://127.0.0.1:3000/api/health",
        ),
    }
    for name, (command, url) in commands.items():
        if name in saved and owned_process(saved[name]) is not None:
            with urllib.request.urlopen(url, timeout=5):
                print(f"{name} already healthy", flush=True)
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


def down():
    if not STATE.exists():
        return
    saved = json.loads(STATE.read_text())
    for name in list(reversed(saved)):
        process = owned_process(saved[name])
        if process is not None:
            # Only a verified, workspace-owned process tree is stopped.
            children = process.children(recursive=True)
            for child in reversed(children):
                child.terminate()
            process.terminate()
            _, alive = psutil.wait_procs([process, *children], timeout=10)
            if alive:
                raise RuntimeError(f"{name} did not stop; keeping process state for inspection")
        del saved[name]
        STATE.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    STATE.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down"])
    {"up": up, "down": down}[parser.parse_args().action]()
