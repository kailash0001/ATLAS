"""Manage only the named local kind-aegis context; no implicit current-context writes."""

import argparse
import json
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, stdin=None):
    return subprocess.run(args, cwd=ROOT, input=stdin, text=True, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "deploy", "status"])
    args = parser.parse_args()
    for tool in ["docker", "kind", "kubectl"]:
        if not shutil.which(tool):
            raise SystemExit(f"Install {tool} before using kind deployment")
    run("docker", "info", "--format", "{{.ServerVersion}}")
    if args.action == "up":
        clusters = subprocess.check_output(["kind", "get", "clusters"], text=True).splitlines()
        if "aegis" not in clusters:
            run(
                "kind",
                "create",
                "cluster",
                "--name",
                "aegis",
                "--config",
                "infrastructure/kind/cluster.yaml",
                "--wait",
                "120s",
            )
        return
    kubectl = ["kubectl", "--context", "kind-aegis", "-n", "aegis"]
    if args.action == "status":
        run(*kubectl, "get", "pods,services,deployments")
        return
    run(
        "docker",
        "build",
        "-f",
        "infrastructure/containers/platform.Dockerfile",
        "-t",
        "aegis-platform:local",
        ".",
    )
    run("kind", "load", "docker-image", "aegis-platform:local", "--name", "aegis")
    run(
        *kubectl,
        "apply",
        "-f",
        "-",
        stdin=json.dumps({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "aegis"}}),
    )
    token_path = ROOT / ".local" / "kind-control-token"
    token_path.parent.mkdir(exist_ok=True)
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "aegis-platform", "namespace": "aegis"},
        "stringData": {
            "AEGIS_DATABASE_URL": "postgresql+psycopg://aegis:aegis_local@postgres:5432/aegis",
            "AEGIS_MLFLOW_TRACKING_URI": "http://mlflow:5000",
            "AEGIS_DATA_ROOT": "/app/data",
            "AEGIS_CONTROL_TOKEN": token_path.read_text(encoding="utf-8"),
            "AEGIS_ACTOR": "kind-operator",
            "AEGIS_PROMETHEUS_URL": "http://prometheus:9090",
        },
    }
    run(*kubectl, "apply", "-f", "-", stdin=json.dumps(secret))
    run(*kubectl, "apply", "-f", "infrastructure/kubernetes/platform.yaml")
    for name in ["postgres", "mlflow", "control-api"]:
        run(*kubectl, "rollout", "status", f"deployment/{name}", "--timeout=240s")
    print("Control API: http://127.0.0.1:18100; operator token stored in .local/kind-control-token")


if __name__ == "__main__":
    main()
