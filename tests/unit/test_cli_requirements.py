from pathlib import Path

from typer.testing import CliRunner

from specwatch.cli import app

runner = CliRunner()

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "sample_prd.md").read_text()


def test_requirements_list_empty_before_extract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["requirements", "list"])
    assert result.exit_code == 0
    assert "No requirements found" in result.output


def test_extract_then_list_then_show(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    prd_path = tmp_path / "prd.md"
    prd_path.write_text(FIXTURE)

    extract_result = runner.invoke(app, ["requirements", "extract", str(prd_path)])
    assert extract_result.exit_code == 0
    assert "Extracted 3 requirement(s)" in extract_result.output

    list_result = runner.invoke(app, ["requirements", "list"])
    assert list_result.exit_code == 0
    assert "Invoice Approval" in list_result.output
    assert "requirement/active" in list_result.output
    assert "architecture_rule/active" in list_result.output

    first_id = list_result.output.splitlines()[0].split()[0]
    show_result = runner.invoke(app, ["requirements", "show", first_id])
    assert show_result.exit_code == 0
    assert first_id in show_result.output


def test_show_unknown_id_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["requirements", "show", "REQ-NOPE00"])
    assert result.exit_code == 1
    assert "Unknown requirement" in result.output
