"""Deduplicate verified, publish-decision findings by
(primary requirement, subsystem, verdict), keeping the highest-confidence
one per group. Suppressed/abstained results are never deduplicated --
they're not going to be published either way."""

from specwatch.domain.models import FindingCandidate
from specwatch.verification.verifier import VerificationResult


def deduplicate_verified_findings(results: list[VerificationResult]) -> list[VerificationResult]:
    best: dict[tuple, VerificationResult] = {}
    others: list[VerificationResult] = []

    for result in results:
        if result.decision != "publish":
            others.append(result)
            continue
        key = _dedupe_key(result.finding)
        current = best.get(key)
        if current is None or result.computed_confidence > current.computed_confidence:
            best[key] = result

    return [*best.values(), *others]


def _dedupe_key(finding: FindingCandidate) -> tuple:
    primary_requirement = finding.requirement_ids[0] if finding.requirement_ids else ""
    return (primary_requirement, _subsystem(finding), finding.verdict.value)


def _subsystem(finding: FindingCandidate) -> str:
    """A coarse "which part of the codebase" grouping key -- the first
    two dotted segments of the first changed symbol's qualified name
    (e.g. "app.services" for "app.services.invoice_service.InvoiceService.send")."""
    if not finding.changed_symbol_ids:
        return ""
    parts = finding.changed_symbol_ids[0].split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else parts[0]
