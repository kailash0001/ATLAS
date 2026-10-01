import hashlib
import os
import subprocess
import sys
from pathlib import Path

from aegis.db.models import AuditEvent, VerificationRun
from aegis.reliability.service import serialize

ROOT = Path(__file__).resolve().parents[2]


def source_hash():
    digest = hashlib.sha256()
    files = []
    excluded = {"node_modules", ".next", "test-results", "playwright-report", "__pycache__"}
    for directory in ("aegis", "apps", "tests", "configs", "migrations", "dags"):
        for root, directories, names in os.walk(ROOT / directory):
            directories[:] = [d for d in directories if d not in excluded]
            files.extend(
                Path(root) / name
                for name in names
                if Path(name).suffix in {".py", ".yaml", ".ts", ".tsx", ".css", ".json"}
            )
    files += [ROOT / "pyproject.toml", ROOT / "requirements.lock"]
    for path in sorted(files):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def verify(factory, actor):
    before = source_hash()
    commands = {
        "lint": ["ruff", "check", "."],
        "format": ["ruff", "format", "--check", "."],
        "dependencies": ["pip", "check"],
        "unit": ["pytest", "tests/unit", "-q"],
        "integration": ["pytest", "tests/integration", "-q"],
    }
    results = {}
    for name, arguments in commands.items():
        try:
            completed = subprocess.run(
                [sys.executable, "-m", *arguments], cwd=ROOT, capture_output=True, timeout=600
            )
            output = completed.stdout + completed.stderr
            results[name] = {
                "returncode": completed.returncode,
                "command": arguments,
                "output_sha256": hashlib.sha256(output).hexdigest(),
                "summary": output.decode(errors="replace")[-4000:],
            }
        except subprocess.TimeoutExpired:
            results[name] = {"returncode": -1, "error": "TIMEOUT"}
    passed = before == source_hash() and all(r["returncode"] == 0 for r in results.values())
    with factory.begin() as session:
        row = VerificationRun(source_hash=before, passed=passed, results=results)
        session.add(row)
        session.flush()
        session.add(
            AuditEvent(
                actor=actor,
                action="remediation.verified",
                resource_type="verification",
                resource_id=row.id,
                details={"passed": passed},
            )
        )
        return serialize(row)
