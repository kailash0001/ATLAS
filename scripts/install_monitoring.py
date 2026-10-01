"""Download pinned official Windows monitoring binaries into .local/tools."""

import hashlib
import json
import os
import tarfile
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install(name, spec):
    folder = ROOT / ".local" / "tools" / name
    marker = folder / "installed.json"
    if marker.exists():
        saved = json.loads(marker.read_text())
        if saved["sha256"] == spec["sha256"] and Path(saved["executable"]).is_file():
            return {"service": name, "status": "already installed"}
        raise RuntimeError(f"Existing {name} installation does not match pinned release")
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / spec["url"].rsplit("/", 1)[1]
    if not archive.exists():
        print(f"Downloading {name} {spec['version']}...", flush=True)
        with (
            urllib.request.urlopen(spec["url"], timeout=60) as response,
            archive.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != spec["sha256"]:
        raise RuntimeError(f"{name} checksum mismatch; remove the incomplete archive and retry")
    print(f"Verified {name}; extracting...", flush=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.namelist():
                if not (folder / member).resolve().is_relative_to(folder.resolve()):
                    raise RuntimeError("Unsafe archive path")
            zipped.extractall(folder)
    else:
        with tarfile.open(archive) as tar:
            tar.extractall(folder, filter="data")
    executables = list(folder.rglob(spec["executable"]))
    if len(executables) != 1:
        raise RuntimeError(f"Expected one {spec['executable']}")
    marker.write_text(json.dumps({**spec, "executable": str(executables[0])}, indent=2))
    return {"service": name, "version": spec["version"], "status": "installed and verified"}


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Use Docker Compose on non-Windows systems")
    releases = json.loads((ROOT / "infrastructure/monitoring-releases.json").read_text())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(install, name, spec) for name, spec in releases.items()]
        for future in futures:
            print(json.dumps(future.result()), flush=True)
