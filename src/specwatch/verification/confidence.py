"""Confidence scoring.

The model's self-reported confidence is one input among several, never
trusted alone (plan.md §21). Weights and soft caps are a starting
rubric, not a calibrated model -- tune with evaluation, per the plan.
"""

from specwatch.agent.state import EvidenceItem
from specwatch.agent.tools.context import ToolContext
from specwatch.domain.models import FindingCandidate

_MODEL_CONFIDENCE_WEIGHT = 0.35
_MAPPING_STRENGTH_WEIGHT = 0.25
_CITATION_STRENGTH_WEIGHT = 0.20
_EVIDENCE_DIVERSITY_WEIGHT = 0.20

_MAPPING_SCORE_SOFT_CAP = 3.0  # a BM25 candidate score at/above this counts as "strong"
_CITATION_SOFT_CAP = 2  # 2+ citations gets full credit for this factor
_DIVERSITY_SOFT_CAP = 3  # 3+ distinct tool types used gets full credit


def compute_confidence(
    candidate: FindingCandidate, evidence_items: list[EvidenceItem], context: ToolContext
) -> float:
    model_confidence = max(0.0, min(1.0, candidate.model_confidence))
    mapping_strength = _mapping_strength(candidate, context)
    citation_strength = min(1.0, len(candidate.citations) / _CITATION_SOFT_CAP)
    evidence_diversity = min(1.0, len({item.tool_name for item in evidence_items}) / _DIVERSITY_SOFT_CAP)

    score = (
        _MODEL_CONFIDENCE_WEIGHT * model_confidence
        + _MAPPING_STRENGTH_WEIGHT * mapping_strength
        + _CITATION_STRENGTH_WEIGHT * citation_strength
        + _EVIDENCE_DIVERSITY_WEIGHT * evidence_diversity
    )
    return round(max(0.0, min(1.0, score)), 4)


def _mapping_strength(candidate: FindingCandidate, context: ToolContext) -> float:
    """How strongly Phase 4's deterministic candidate generation already
    linked the cited requirement(s) to the cited changed symbol(s)."""
    best_scores: list[float] = []
    for requirement_id in candidate.requirement_ids:
        symbol_candidates = context.candidate_repo.symbol_candidates_for_requirement(requirement_id)
        matches = [c.score for c in symbol_candidates if c.symbol_qualified_name in candidate.changed_symbol_ids]
        if matches:
            best_scores.append(max(matches))
    if not best_scores:
        return 0.0
    return min(1.0, max(best_scores) / _MAPPING_SCORE_SOFT_CAP)
