from pathlib import Path

from typer.testing import CliRunner

from specwatch.cli import app

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "specwatch" in result.output.lower()


def test_config_validate_succeeds_with_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "Configuration valid" in result.output


def test_config_validate_fails_on_bad_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "specwatch.yml").write_text("min_confidence: 5\n")
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 1
    assert "Invalid configuration" in result.output
