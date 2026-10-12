"""Phase 1 acceptance criteria, verified end to end:

1. a sample PRD produces useful requirements
2. all requirements cite their exact source
3. unrelated line movement does not change requirement IDs
"""

from pathlib import Path

from specwatch.specs.extractor import extract_requirements

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "sample_prd.md"


def test_sample_prd_produces_useful_requirements() -> None:
    requirements = extract_requirements(FIXTURE_PATH.read_text(), source_file="prd.md")

    assert len(requirements) == 3
    titles = {r.title for r in requirements}
    assert titles == {"Invoice Approval", "Password Reset Tokens", "Layering"}


def test_requirements_cite_exact_source() -> None:
    text = FIXTURE_PATH.read_text()
    lines = text.splitlines()

    for requirement in extract_requirements(text, source_file="prd.md"):
        cited_text = "\n".join(lines[requirement.source.line_start - 1 : requirement.source.line_end])
        # every word of the (whitespace-normalized) statement must be traceable
        # back to the literal cited lines
        for word in requirement.statement.split():
            assert word in cited_text


def test_unrelated_line_movement_does_not_change_ids() -> None:
    original_text = FIXTURE_PATH.read_text()
    original_ids = {r.title: r.id for r in extract_requirements(original_text, source_file="prd.md")}

    # shift every subsequent line's number by inserting blank lines at
    # several points; headings and requirement statement text are
    # byte-for-byte untouched, only line numbers move
    perturbed_text = (
        "\n\n\n"
        + original_text.replace("## Invoice Sending\n", "## Invoice Sending\n\n\n\n")
        .replace("## Architecture\n", "\n\n## Architecture\n")
        .replace("## Non-Goals\n", "\n\n\n\n## Non-Goals\n")
    )
    assert perturbed_text != original_text

    perturbed_sections = {
        r.title: (r.id, r.source.line_start)
        for r in extract_requirements(perturbed_text, source_file="prd.md")
    }
    original_sections = {
        r.title: r.source.line_start
        for r in extract_requirements(original_text, source_file="prd.md")
    }

    # sanity check the perturbation actually moved lines, so this test
    # would fail if segmentation stopped shifting line numbers correctly
    for title, (_, new_line_start) in perturbed_sections.items():
        assert new_line_start != original_sections[title]

    perturbed_ids = {title: req_id for title, (req_id, _) in perturbed_sections.items()}
    assert perturbed_ids == original_ids
