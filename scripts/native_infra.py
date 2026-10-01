"""Windows development services using installed PostgreSQL and workspace-local data.

Run `python scripts/native_infra.py up` (or `down`). No Windows services are
installed; existing PostgreSQL clusters are never touched.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
CLUSTER = LOCAL / "postgres"
STATE = LOCAL / "native.json"
PG_PORT = 55432
MLFLOW_PORT = 55000
PASSWORD = "aegis_local"


def pg_bin() -> Path:
    override = os.environ.get("AEGIS_PG_BIN")
    if override:
        return Path(override)
    found = shutil.which("pg_ctl")
    if found:
        return Path(found).parent
    for major in (17, 18):
        candidate = Path(f"C:/Program Files/PostgreSQL/{major}/bin")
        if (candidate / "pg_ctl.exe").exists():
            return candidate
    raise RuntimeError("PostgreSQL binaries not found. Set AEGIS_PG_BIN or use Docker Compose.")


def run_pg(binary: str, *args: str, check: bool = True):
    return subprocess.run(
        [str(pg_bin() / binary), *args],
        check=check,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def connection(database="postgres"):
    return psycopg.connect(
        host="127.0.0.1",
        port=PG_PORT,
        user="aegis",
        password=PASSWORD,
        dbname=database,
        connect_timeout=3,
        autocommit=True,
    )


def up():
    LOCAL.mkdir(exist_ok=True)
    env_path = ROOT / ".env"
    desired = (
        f"AEGIS_DATABASE_URL=postgresql+psycopg://aegis:{PASSWORD}@127.0.0.1:{PG_PORT}/aegis\n"
        f"AEGIS_MLFLOW_TRACKING_URI=http://127.0.0.1:{MLFLOW_PORT}\n"
        "AEGIS_ENVIRONMENT=development\nAEGIS_ACTOR=local-developer\nAEGIS_DATA_ROOT=data\n"
    )
    if env_path.exists():
        current = dotenv_values(env_path)
        endpoints = dict(line.split("=", 1) for line in desired.splitlines()[:2])
        if any(current.get(key) != value for key, value in endpoints.items()):
            raise RuntimeError(
                "Existing .env endpoints differ. Back it up before choosing native infrastructure."
            )
    if not (CLUSTER / "PG_VERSION").exists():
        password_file = LOCAL / "init-password"
        try:
            password_file.write_text(PASSWORD, encoding="utf-8")
            run_pg(
                "initdb",
                "-D",
                str(CLUSTER),
                "-U",
                "aegis",
                "--encoding=UTF8",
                "--locale=C",
                "--auth=scram-sha-256",
                f"--pwfile={password_file}",
            )
        finally:
            password_file.unlink(missing_ok=True)
    status = run_pg("pg_ctl", "-D", str(CLUSTER), "status", check=False)
    if status.returncode:
        run_pg(
            "pg_ctl",
            "-D",
            str(CLUSTER),
            "-l",
            str(LOCAL / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {PG_PORT}",
            "-w",
            "start",
        )
    with connection() as conn:
        for database in ("aegis", "mlflow"):
            if not conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
            ).fetchone():
                conn.execute(
                    psycopg.sql.SQL("CREATE DATABASE {} OWNER aegis").format(
                        psycopg.sql.Identifier(database)
                    )
                )
    if not env_path.exists():
        env_path.write_text(desired, encoding="utf-8")
    health = f"http://127.0.0.1:{MLFLOW_PORT}/health"
    if STATE.exists():
        try:
            with urllib.request.urlopen(health, timeout=2) as response:
                if response.status == 200:
                    print("Native services already healthy.")
                    return
        except OSError:
            pass
    artifacts = LOCAL / "mlflow-artifacts"
    artifacts.mkdir(exist_ok=True)
    env = {**os.environ, "MLFLOW_ENABLE_TELEMETRY": "false"}
    with (LOCAL / "mlflow.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mlflow",
                "server",
                "--host",
                "127.0.0.1",
                "--port",
                str(MLFLOW_PORT),
                "--workers",
                "1",
                "--backend-store-uri",
                f"postgresql+psycopg://aegis:{PASSWORD}@127.0.0.1:{PG_PORT}/mlflow",
                "--serve-artifacts",
                "--artifacts-destination",
                artifacts.as_uri(),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
    STATE.write_text(json.dumps({"mlflow_pid": process.pid}), encoding="utf-8")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("MLflow exited. See .local/mlflow.log")
        try:
            with urllib.request.urlopen(health, timeout=2) as response:
                if response.status == 200:
                    print(
                        f"PostgreSQL: 127.0.0.1:{PG_PORT}; MLflow: {health.removesuffix('/health')}"
                    )
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError("MLflow health check timed out. See .local/mlflow.log")


def down():
    if STATE.exists():
        # Verify the saved process identity before signalling a possibly reused PID.
        import psutil

        pid = json.loads(STATE.read_text(encoding="utf-8"))["mlflow_pid"]
        try:
            process = psutil.Process(pid)
            args = process.cmdline()
            if (
                "mlflow" not in args
                or "server" not in args
                or str(MLFLOW_PORT) not in args
                or Path(process.cwd()).resolve() != ROOT
            ):
                raise RuntimeError(
                    "Saved PID is not this workspace's MLflow server; refusing to stop"
                )
            children = process.children(recursive=True)
            for child in reversed(children):
                child.terminate()
            process.terminate()
            psutil.wait_procs([process, *children], timeout=10)
        except psutil.NoSuchProcess:
            pass
        STATE.unlink()
    if (CLUSTER / "PG_VERSION").exists():
        run_pg("pg_ctl", "-D", str(CLUSTER), "-m", "fast", "-w", "stop", check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down"])
    args = parser.parse_args()
    {"up": up, "down": down}[args.action]()
