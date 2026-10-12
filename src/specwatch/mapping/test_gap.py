"""Deterministic negative-case test-gap signal.

Static analysis cannot prove no test exists for a given behavior in
every possible runtime path (plan.md §3.3) -- this only flags
requirements whose statement uses prohibition/denial language and have
zero candidate test coverage at all, as a hint for the agent to
investigate, never as a standalone verdict. Thin-but-nonzero coverage
needs the agent's judgment (does an existing test actually cover the
negative case?), not a blanket deterministic flag.
"""

import re

from specwatch.domain.models import Requirement, RequirementTestCandidate

_NEGATION_RE = re.compile(
    r"\b(must not|may not|cannot|can not|shall not|shall be denied|is prohibited|"
    r"are prohibited|is denied|are denied|is forbidden|are forbidden|not be able to|"
    r"unauthorized|non-member|not a member|must deny|deny access)\b",
    re.IGNORECASE,
)


def has_negative_case_language(statement: str) -> bool:
    """Whether a requirement's statement discusses a prohibition or
    denial -- the kind of behavior that specifically needs a *negative*
    test case, not just a happy-path one."""
    return bool(_NEGATION_RE.search(statement))


def has_test_evidence_gap(
    requirement: Requirement, test_candidates: list[RequirementTestCandidate]
) -> bool:
    """True when a requirement discusses prohibition/denial and has zero
    candidate tests at all."""
    return has_negative_case_language(requirement.statement) and not test_candidates
