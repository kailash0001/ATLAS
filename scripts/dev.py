"""Cross-platform task runner. Invoke with the project virtualenv's Python."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
TASKS = {
    "console-up": [[PYTHON, "scripts/native_console.py", "up"]],
    "console-down": [[PYTHON, "scripts/native_console.py", "down"]],
    "control-api": [
        [
            PYTHON,
            "-m",
            "uvicorn",
            "apps.control_api.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8100",
        ]
    ],
    "kind-up": [[PYTHON, "scripts/kubernetes.py", "up"]],
    "k8s-deploy": [[PYTHON, "scripts/kubernetes.py", "deploy"]],
    "k8s-status": [[PYTHON, "scripts/kubernetes.py", "status"]],
    "train-energy": [
        [PYTHON, "-m", "aegis.cli.main", "train", "--config", "configs/models/energy.yaml"]
    ],
    "investigation-demo": [[PYTHON, "scripts/verify_phase4.py"]],
    "api": [
        [
            PYTHON,
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
        ]
    ],
    "serving-up": [["docker", "compose", "--profile", "serving", "up", "-d", "--build"]],
    "serving-down": [
        ["docker", "compose", "--profile", "serving", "stop", "inference", "prometheus", "grafana"]
    ],
    "traffic": [[PYTHON, "scripts/traffic.py", "--labels"]],
    "infra-up": [["docker", "compose", "up", "-d", "--build", "--wait", "--wait-timeout", "240"]],
    "infra-down": [["docker", "compose", "down"]],
    "migrate": [[PYTHON, "-m", "aegis.cli.main", "db", "upgrade"]],
    "data": [[PYTHON, "-m", "aegis.cli.main", "data", "setup"]],
    "train-fraud": [[PYTHON, "-m", "aegis.cli.main", "train"]],
    "train-maintenance": [
        [PYTHON, "-m", "aegis.cli.main", "train", "--config", "configs/models/maintenance.yaml"]
    ],
    "reliability-demo": [[PYTHON, "scripts/verify_phase3.py"]],
    "test": [[PYTHON, "-m", "pytest", "--cov=aegis", "--cov=apps", "--cov-report=term-missing"]],
    "lint": [
        [PYTHON, "-m", "ruff", "check", "."],
        [PYTHON, "-m", "ruff", "format", "--check", "."],
    ],
    "doctor": [[PYTHON, "-m", "aegis.cli.main", "doctor"]],
    "demo": [
        [PYTHON, "-m", "aegis.cli.main", "db", "upgrade"],
        [PYTHON, "-m", "aegis.cli.main", "train"],
        [PYTHON, "-m", "aegis.cli.main", "models", "compare", "fraud-detector"],
    ],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=TASKS)
    args = parser.parse_args()
    for cmd in TASKS[args.task]:
        subprocess.run(cmd, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
