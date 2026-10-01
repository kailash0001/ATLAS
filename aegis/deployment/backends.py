import os
import time
from pathlib import Path

import httpx

from aegis.core.errors import AegisError


class Backends:
    def __init__(self, settings, runtime):
        self.settings, self.runtime = settings, runtime

    def url(self, version_id):
        return f"http://version-{version_id}.aegis.svc.cluster.local:8000"

    def prepare(self, backend, version_id):
        if backend == "native":
            self.runtime.load(version_id)
            return
        if backend != "kubernetes":
            raise AegisError("Unknown deployment backend")
        # In-cluster API, scoped to the aegis namespace by RBAC. No shell commands.
        account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        if not (account / "token").exists():
            raise AegisError("Kubernetes backend requires the in-cluster control API")
        import ssl

        host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        headers = {"Authorization": f"Bearer {(account / 'token').read_text().strip()}"}
        name = f"version-{version_id}"
        labels = {"app": name}
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": 10002,
                            "fsGroup": 10002,
                        },
                        "containers": [
                            {
                                "name": "runtime",
                                "image": self.settings.runtime_image,
                                "imagePullPolicy": "IfNotPresent",
                                "args": [
                                    "uvicorn",
                                    "apps.runtime.main:create_app",
                                    "--factory",
                                    "--host",
                                    "0.0.0.0",
                                    "--port",
                                    "8000",
                                ],
                                "env": [
                                    {"name": "AEGIS_RUNTIME_VERSION_ID", "value": version_id},
                                    *[
                                        {
                                            "name": key,
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "name": "aegis-platform",
                                                    "key": key,
                                                }
                                            },
                                        }
                                        for key in (
                                            "AEGIS_DATABASE_URL",
                                            "AEGIS_MLFLOW_TRACKING_URI",
                                            "AEGIS_DATA_ROOT",
                                        )
                                    ],
                                ],
                                "ports": [{"containerPort": 8000}],
                                "readinessProbe": {
                                    "httpGet": {"path": "/health/ready", "port": 8000},
                                    "initialDelaySeconds": 5,
                                    "periodSeconds": 5,
                                },
                                "livenessProbe": {
                                    "httpGet": {"path": "/health/live", "port": 8000},
                                    "initialDelaySeconds": 120,
                                },
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "512Mi"},
                                    "limits": {"cpu": "2", "memory": "2Gi"},
                                },
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                                "volumeMounts": [
                                    {"name": "data", "mountPath": "/app/data", "readOnly": True}
                                ],
                            }
                        ],
                        "volumes": [
                            {
                                "name": "data",
                                "hostPath": {"path": "/aegis-data", "type": "Directory"},
                            }
                        ],
                    },
                },
            },
        }
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name},
            "spec": {"selector": labels, "ports": [{"port": 8000, "targetPort": 8000}]},
        }
        with httpx.Client(
            base_url=f"https://{host}",
            headers=headers,
            verify=ssl.create_default_context(cafile=str(account / "ca.crt")),
            timeout=15,
        ) as client:
            for prefix, plural, body in [
                ("/apis/apps/v1", "deployments", deployment),
                ("/api/v1", "services", service),
            ]:
                response = client.post(f"{prefix}/namespaces/aegis/{plural}", json=body)
                if response.status_code != 409:
                    response.raise_for_status()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                self.ready(backend, version_id)
                return
            except (httpx.HTTPError, AegisError):
                time.sleep(2)
        raise AegisError("Version runtime did not become ready within 180 seconds")

    def ready(self, backend, version_id):
        if backend == "native":
            self.runtime.load(version_id)
        else:
            response = httpx.get(self.url(version_id) + "/health/ready", timeout=5)
            response.raise_for_status()
            if response.json().get("version_id") != version_id:
                raise AegisError("Runtime identity mismatch")

    def predict(self, backend, version_id, features):
        if backend == "native":
            return self.runtime.predict(version_id, features)
        response = httpx.post(
            self.url(version_id) + "/predict", json={"features": features}, timeout=10
        )
        response.raise_for_status()
        result = response.json()
        if result.get("version_id") != version_id:
            raise AegisError("Runtime identity mismatch")
        return float(result["prediction"])
