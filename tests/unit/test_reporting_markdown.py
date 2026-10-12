from specwatch.domain.enums import FindingVerdict
from specwatch.domain.models import Citation, FindingCandidate
from specwatch.reporting.markdown import render_findings_markdown
from specwatch.verification.verifier import VerificationResult


def _published_result(**overrides) -> VerificationResult:
    defaults = dict(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        requirement_ids=["REQ-1"],
        changed_symbol_ids=["pkg.Foo.bar"],
        summary="Approval guard appears to be missing.",
        reasoning="Inspected the symbol, found no guard, searched elsewhere, found nothing.",
        citations=[Citation(evidence_id="ev-1", file="pkg/foo.py", line_start=10, line_end=12, quote="x")],
        model_confidence=0.9,
    )
    defaults.update(overrides)
    finding = FindingCandidate(**defaults)
    return VerificationResult(decision="publish", computed_confidence=0.85, reasons=[], finding=finding)


def test_no_published_findings_renders_clean_message() -> None:
    suppressed = VerificationResult(
        decision="suppress",
        computed_confidence=0.1,
        reasons=["low confidence"],
        finding=FindingCandidate(
            verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
            summary="s",
            reasoning="r",
            model_confidence=0.1,
        ),
    )
    markdown = render_findings_markdown([suppressed])
    assert "No specification drift findings" in markdown
    assert "SpecWatch" in markdown


def test_published_finding_includes_summary_evidence_and_confidence() -> None:
    markdown = render_findings_markdown([_published_result()])
    assert "Approval guard appears to be missing." in markdown
    assert "REQ-1" in markdown
    assert "pkg/foo.py:10-12" in markdown
    assert "**Confidence:** High" in markdown


def test_multiple_findings_are_all_rendered() -> None:
    a = _published_result(summary="First issue.")
    b = _published_result(summary="Second issue.")
    markdown = render_findings_markdown([a, b])
    assert "First issue." in markdown
    assert "Second issue." in markdown
    assert "2 possible specification conflict(s)" in markdown


def test_unresolved_questions_are_rendered_when_present() -> None:
    markdown = render_findings_markdown(
        [_published_result(unresolved_questions=["Is this intentional?"])]
    )
    assert "Is this intentional?" in markdown


def test_confidence_label_thresholds() -> None:
    high = render_findings_markdown([_published_result()])  # computed_confidence=0.85 fixed above
    assert "High" in high

    very_high_result = _published_result()
    very_high_result = very_high_result.model_copy(update={"computed_confidence": 0.95})
    assert "Very High" in render_findings_markdown([very_high_result])
