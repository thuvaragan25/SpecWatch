from specwatch.domain.enums import FindingVerdict
from specwatch.domain.models import FindingCandidate
from specwatch.verification.dedupe import deduplicate_verified_findings
from specwatch.verification.verifier import VerificationResult


def _result(
    decision: str,
    confidence: float,
    requirement_ids: list[str],
    changed_symbol_ids: list[str],
    verdict: FindingVerdict = FindingVerdict.SPEC_VIOLATION_LIKELY,
) -> VerificationResult:
    finding = FindingCandidate(
        verdict=verdict,
        requirement_ids=requirement_ids,
        changed_symbol_ids=changed_symbol_ids,
        summary="s",
        reasoning="r",
        model_confidence=0.5,
    )
    return VerificationResult(decision=decision, computed_confidence=confidence, reasons=[], finding=finding)


def test_keeps_highest_confidence_within_same_group() -> None:
    low = _result("publish", 0.5, ["REQ-1"], ["pkg.mod.Foo.bar"])
    high = _result("publish", 0.9, ["REQ-1"], ["pkg.mod.Foo.baz"])  # same subsystem "pkg.mod"

    deduped = deduplicate_verified_findings([low, high])

    assert len(deduped) == 1
    assert deduped[0].computed_confidence == 0.9


def test_different_requirements_are_not_merged() -> None:
    a = _result("publish", 0.5, ["REQ-1"], ["pkg.mod.Foo.bar"])
    b = _result("publish", 0.5, ["REQ-2"], ["pkg.mod.Foo.bar"])

    assert len(deduplicate_verified_findings([a, b])) == 2


def test_different_verdicts_are_not_merged() -> None:
    a = _result("publish", 0.5, ["REQ-1"], ["pkg.mod.Foo.bar"], verdict=FindingVerdict.SPEC_VIOLATION_LIKELY)
    b = _result("publish", 0.5, ["REQ-1"], ["pkg.mod.Foo.bar"], verdict=FindingVerdict.SPEC_MAY_BE_STALE)

    assert len(deduplicate_verified_findings([a, b])) == 2


def test_non_publish_results_pass_through_unmerged() -> None:
    a = _result("suppress", 0.1, ["REQ-1"], ["pkg.mod.Foo.bar"])
    b = _result("suppress", 0.2, ["REQ-1"], ["pkg.mod.Foo.bar"])

    assert len(deduplicate_verified_findings([a, b])) == 2
