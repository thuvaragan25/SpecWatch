from pathlib import Path

from specwatch.domain.enums import PassageType
from specwatch.specs.extractor import classify_section, extract_requirements
from specwatch.specs.parser import segment_markdown

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "sample_prd.md").read_text()


def test_classify_section_heuristics() -> None:
    sections = {s.heading: s for s in segment_markdown(FIXTURE)}
    assert classify_section(sections["Invoice Approval"]) == PassageType.REQUIREMENT
    assert classify_section(sections["Password Reset Tokens"]) == PassageType.REQUIREMENT
    assert classify_section(sections["Layering"]) == PassageType.ARCHITECTURE_RULE
    assert classify_section(sections["Non-Goals"]) == PassageType.NON_GOAL
    assert classify_section(sections["Examples"]) == PassageType.EXAMPLE
    assert classify_section(sections["Background"]) == PassageType.CONTEXT


def test_extract_requirements_only_includes_requirements_and_architecture_rules() -> None:
    requirements = extract_requirements(FIXTURE, source_file="prd.md")
    titles = {r.title for r in requirements}
    assert titles == {"Invoice Approval", "Password Reset Tokens", "Layering"}


def test_extracted_requirement_cites_exact_source() -> None:
    requirements = extract_requirements(FIXTURE, source_file="prd.md")
    approval = next(r for r in requirements if r.title == "Invoice Approval")
    lines = FIXTURE.splitlines()
    cited = "\n".join(lines[approval.source.line_start - 1 : approval.source.line_end])
    assert "must be explicitly approved" in cited


def test_extract_requirements_skips_empty_body_sections() -> None:
    text = "### Heading With No Body\n### Next\n\nThis must happen.\n"
    requirements = extract_requirements(text, source_file="x.md")
    assert len(requirements) == 1
    assert requirements[0].title == "Next"
