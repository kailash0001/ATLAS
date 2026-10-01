import json

import pytest

from aegis.core.errors import DataIntegrityError
from aegis.data.fraud import load_dataset, setup_dataset


def test_reproducible_disjoint_splits(config, tmp_path):
    first = setup_dataset(config.dataset, tmp_path / "a")
    second = setup_dataset(config.dataset, tmp_path / "b")
    assert first.name == second.name
    manifest, frames = load_dataset(first)
    assert sum(len(f) for f in frames.values()) == config.dataset.samples
    assert 0.02 < frames["train"].is_fraud.mean() < 0.3
    assert setup_dataset(config.dataset, tmp_path / "a") == first
    config.dataset.seed += 1
    assert setup_dataset(config.dataset, tmp_path / "a").name != manifest["fingerprint"]


def test_reject_modified_data(config, tmp_path):
    path = setup_dataset(config.dataset, tmp_path)
    with (path / "train.csv").open("a") as file:
        file.write("corruption")
    with pytest.raises(DataIntegrityError, match="checksum"):
        load_dataset(path)
    with pytest.raises(DataIntegrityError):
        setup_dataset(config.dataset, tmp_path)


def test_reject_modified_manifest(config, tmp_path):
    path = setup_dataset(config.dataset, tmp_path)
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["generator"]["seed"] = 99
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DataIntegrityError, match="fingerprint"):
        load_dataset(path)
