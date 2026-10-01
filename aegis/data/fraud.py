import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from aegis.core.config import DatasetConfig
from aegis.core.errors import DataIntegrityError

SPLITS = ("train", "validation", "test")
SOURCE = "AegisML synthetic fraud generator v1; no real customer data"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def generate(config: DatasetConfig) -> pd.DataFrame:
    """A noisy, imbalanced synthetic workload, not a financial benchmark."""
    if config.name == "maintenance-synthetic":
        from aegis.data.maintenance import generate as maintenance_generate

        return maintenance_generate(config)
    rng = np.random.default_rng(config.seed)
    n = config.samples
    frame = pd.DataFrame(
        {
            "amount": np.round(rng.lognormal(3.5, 1.1, n), 2),
            "hour": rng.integers(0, 24, n),
            "distance_from_home": np.round(rng.exponential(25, n), 2),
            "transactions_24h": rng.poisson(3, n),
            "account_age_days": rng.integers(1, 3650, n),
            "merchant_category": rng.choice(
                ["grocery", "travel", "electronics", "entertainment"], n
            ),
            "card_present": rng.choice(["yes", "no"], n, p=[0.65, 0.35]),
        }
    )
    risk = (
        -4.8
        + 1.6 * (frame.amount > 120)
        + 1.5 * (frame.hour < 5)
        + 1.3 * (frame.distance_from_home > 65)
        + 1.2 * (frame.transactions_24h > 5)
        + 1.1 * (frame.account_age_days < 120)
        + 0.9 * (frame.card_present == "no")
        + 1.0 * ((frame.merchant_category == "electronics") & (frame.card_present == "no"))
    )
    frame["is_fraud"] = rng.binomial(1, 1 / (1 + np.exp(-risk)))
    frame.insert(0, "transaction_id", [f"txn-{config.seed}-{i:08d}" for i in range(n)])
    return frame


def setup_dataset(config: DatasetConfig, root: Path) -> Path:
    if config.name == "energy-synthetic":
        from aegis.data.energy import setup_dataset as setup_energy

        return setup_energy(config, root)
    root = root.resolve() / config.name
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".building-", dir=root) as temporary:
        staging = Path(temporary)
        frame = generate(config)
        target = "failure" if config.name == "maintenance-synthetic" else "is_fraud"
        train, holdout = train_test_split(
            frame,
            test_size=config.test_fraction + config.validation_fraction,
            random_state=config.seed,
            stratify=frame[target],
        )
        validation, test = train_test_split(
            holdout,
            test_size=config.test_fraction / (config.test_fraction + config.validation_fraction),
            random_state=config.seed,
            stratify=holdout[target],
        )
        manifest = {"source": SOURCE, "generator": config.model_dump(), "splits": {}}
        if target == "failure":
            manifest["source"] = "AegisML synthetic industrial sensors v1; no real equipment data"
        for name, split in zip(SPLITS, (train, validation, test), strict=True):
            path = staging / f"{name}.csv"
            split.to_csv(path, index=False, lineterminator="\n")
            manifest["splits"][name] = {"sha256": digest(path.read_bytes()), "rows": len(split)}
        fingerprint = digest(canonical(manifest))
        manifest["fingerprint"] = fingerprint
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        destination = root / fingerprint
        if destination.exists():
            load_dataset(destination)
        else:
            shutil.copytree(staging, destination)
    return destination


def load_dataset(path: Path) -> tuple[dict, dict[str, pd.DataFrame]]:
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        unsigned = {k: v for k, v in manifest.items() if k != "fingerprint"}
        if digest(canonical(unsigned)) != manifest["fingerprint"]:
            raise DataIntegrityError("Dataset manifest fingerprint mismatch")
        if set(manifest["splits"]) != set(SPLITS):
            raise DataIntegrityError("Dataset must contain train, validation and test splits")
        frames = {}
        identifiers: set[str] = set()
        for split in SPLITS:
            file = path / f"{split}.csv"
            expected = manifest["splits"][split]
            if digest(file.read_bytes()) != expected["sha256"]:
                raise DataIntegrityError(f"Dataset checksum mismatch: {split}")
            frame = pd.read_csv(file)
            if len(frame) != expected["rows"]:
                raise DataIntegrityError(f"Dataset row count mismatch: {split}")
            if manifest["generator"]["name"] == "energy-synthetic":
                from aegis.data.energy import validate_split

                validate_split(frame, frames)
                frames[split] = frame
                continue
            maintenance = manifest["generator"]["name"] == "maintenance-synthetic"
            ids = set(frame["reading_id" if maintenance else "transaction_id"])
            if len(ids) != len(frame) or identifiers.intersection(ids):
                raise DataIntegrityError("Duplicate transaction IDs or overlapping dataset splits")
            if set(frame["failure" if maintenance else "is_fraud"].unique()) != {0, 1}:
                raise DataIntegrityError(f"Both binary labels are required in {split}")
            identifiers.update(ids)
            frames[split] = frame
        return manifest, frames
    except (OSError, KeyError, ValueError, AttributeError) as exc:
        raise DataIntegrityError(f"Invalid dataset at {path}: {exc}") from exc
