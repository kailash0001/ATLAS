from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from aegis.core.config import load_config
from aegis.db.session import make_engine, sessions


@pytest.fixture
def config():
    config = load_config(Path("configs/models/fraud.yaml"))
    config.dataset.samples = 1000
    config.training.algorithms["random_forest"]["n_estimators"] = 12
    return config


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "aegis.db").as_posix()
    monkeypatch.setenv("AEGIS_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    engine = make_engine(url)
    yield sessions(engine)
    engine.dispose()
