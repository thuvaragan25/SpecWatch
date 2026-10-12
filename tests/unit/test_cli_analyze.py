import shutil
import subprocess
from pathlib import Path

from langchain_core.messages import AIMessage
from typer.testing import CliRunner

import specwatch.cli as cli_module
from specwatch.cli import app

runner = CliRunner()

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "auth_scenario_repo"


class _ImmediateNoIssueFake:
    """Minimal stand-in: every investigation immediately abstains, so the
    CLI command exercises real wiring end to end without needing any
    scripted tool-call reasoning."""

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages, **kwargs):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "submit_finding",
                    "args": {
                        "verdict": "insufficient_evidence",
                        "summary": "s",
                        "reasoning": "r",
                        "model_confidence": 0.1,
                    },
                    "id": "c1",
                }
            ],
        )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_analyze_command_reports_no_findings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    shutil.copytree(FIXTURE_ROOT, tmp_path, dirs_exist_ok=True)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "head")

    index_result = runner.invoke(app, ["index", "--spec", "docs/prd.md"])
    assert index_result.exit_code == 0

    monkeypatch.setattr(cli_module, "create_chat_model", lambda model: _ImmediateNoIssueFake())

    result = runner.invoke(app, ["analyze", "--base", base_sha, "--head", "HEAD"])

    assert result.exit_code == 0
    assert "No specification drift findings." in result.output
