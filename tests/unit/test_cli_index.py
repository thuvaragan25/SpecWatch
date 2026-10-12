import shutil
from pathlib import Path

from typer.testing import CliRunner

from specwatch.cli import app

runner = CliRunner()

FIXTURE_PRD = Path(__file__).parent.parent / "fixtures" / "sample_prd.md"
FIXTURE_CODE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_code_repo"


def _prepare_repo(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURE_CODE_ROOT, tmp_path, dirs_exist_ok=True)
    prd_path = tmp_path / "prd.md"
    prd_path.write_text(FIXTURE_PRD.read_text())
    return prd_path


def test_index_command_reports_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    prd_path = _prepare_repo(tmp_path)

    result = runner.invoke(app, ["index", "--spec", str(prd_path)])

    assert result.exit_code == 0
    assert "Indexed 3 requirement(s)" in result.output
    assert "code symbol(s)" in result.output
    assert "test(s)" in result.output


def test_requirements_show_lists_candidates_after_index(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    prd_path = _prepare_repo(tmp_path)

    runner.invoke(app, ["index", "--spec", str(prd_path)])
    list_result = runner.invoke(app, ["requirements", "list"])
    approval_id = next(
        line.split()[0] for line in list_result.output.splitlines() if "Invoice Approval" in line
    )

    show_result = runner.invoke(app, ["requirements", "show", approval_id])

    assert show_result.exit_code == 0
    assert "Candidate code symbols:" in show_result.output
    assert "app.services.invoice_service.InvoiceService" in show_result.output
    assert "Candidate tests:" in show_result.output
    assert "test_send_invoice_delivers_via_client" in show_result.output
