import json

from typer.testing import CliRunner

from aegis.cli.main import app

runner = CliRunner()


def test_cli_help_and_validated_config():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["config-check"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["configuration"] == "valid"


def test_empty_database_is_honest(database):
    for command in (["models", "list"], ["runs", "list"], ["audit"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == []


def test_missing_promotion_reason_rejected():
    result = runner.invoke(app, ["models", "promote", "fraud-detector", "1"])
    assert result.exit_code == 2


def test_cli_data_setup(config, tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_DATA_ROOT", str(tmp_path))
    result = runner.invoke(app, ["data", "setup"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["fingerprint"]) == 64
