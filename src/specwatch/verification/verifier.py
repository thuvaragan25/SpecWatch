"""The verifier's entry point: verify_finding.

no_issue/insufficient_evidence verdicts are never "published" as PR
findings in the first place -- they abstain by construction, regardless
of citations, since there is nothing actionable to gate. Only the four
actionable verdicts go through provenance/citation/confidence checks.
"""

from typing import Literal

from pydantic import BaseModel

from specwatch.agent.state import EvidenceItem
from specwatch.agent.tools.context import ToolContext
from specwatch.domain.enums import FindingVerdict
from specwatch.domain.models import FindingCandidate
from specwatch.verification.citations import validate_citations
from specwatch.verification.confidence import compute_confidence
from specwatch.verification.provenance import validate_provenance

ACTIONABLE_VERDICTS = {
    FindingVerdict.SPEC_VIOLATION_LIKELY,
    FindingVerdict.SPEC_MAY_BE_STALE,
    FindingVerdict.TEST_EVIDENCE_GAP,
    FindingVerdict.ARCHITECTURE_VIOLATION_LIKELY,
}

PublicationDecision = Literal["publish", "suppress", "abstain"]


class VerificationResult(BaseModel):
    decision: PublicationDecision
    computed_confidence: float
    reasons: list[str]
    finding: FindingCandidate


def verify_finding(
    candidate: FindingCandidate,
    evidence_items: list[EvidenceItem],
    changed_symbol_qualified_names: list[str],
    context: ToolContext,
    min_confidence: float,
) -> VerificationResult:
    """Decide whether a finding may be published, based on provenance,
    citation validity, and the configured publication confidence
    threshold. A finding below the threshold is suppressed, never
    published, regardless of the model's own self-reported confidence."""
    if candidate.verdict not in ACTIONABLE_VERDICTS:
        return VerificationResult(
            decision="abstain",
            computed_confidence=0.0,
            reasons=[f"verdict {candidate.verdict.value!r} is not actionable"],
            finding=candidate,
        )

    reasons: list[str] = []
    reasons.extend(validate_provenance(candidate, changed_symbol_qualified_names, context))

    if not candidate.citations:
        reasons.append("actionable verdict has no citations")
    else:
        reasons.extend(
            f"invalid citation (evidence_id={issue.citation.evidence_id!r}): {issue.reason}"
            for issue in validate_citations(candidate.citations, evidence_items, context)
        )

    if reasons:
        return VerificationResult(decision="suppress", computed_confidence=0.0, reasons=reasons, finding=candidate)

    computed_confidence = compute_confidence(candidate, evidence_items, context)
    if computed_confidence < min_confidence:
        return VerificationResult(
            decision="suppress",
            computed_confidence=computed_confidence,
            reasons=[f"confidence {computed_confidence:.2f} below threshold {min_confidence:.2f}"],
            finding=candidate,
        )

    return VerificationResult(decision="publish", computed_confidence=computed_confidence, reasons=[], finding=candidate)
