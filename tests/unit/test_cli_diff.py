import subprocess
from pathlib import Path

from typer.testing import CliRunner

from specwatch.cli import app

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_diff_command_reports_changed_files_and_symbols(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")

    module = tmp_path / "service.py"
    module.write_text("def send(x):\n    return x\n")
    _git(tmp_path, "add", "service.py")
    _git(tmp_path, "commit", "-q", "-m", "base")

    module.write_text("def send(x):\n    return x + 1\n")
    _git(tmp_path, "commit", "-q", "-am", "head")

    result = runner.invoke(app, ["diff", "--base", "HEAD~1", "--head", "HEAD"])

    assert result.exit_code == 0
    assert "service.py" in result.output
    assert "service.send" in result.output


def test_diff_command_reports_no_changes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-q", "-m", "only commit")

    result = runner.invoke(app, ["diff", "--base", "HEAD", "--head", "HEAD"])

    assert result.exit_code == 0
    assert "No changed Python files" in result.output
