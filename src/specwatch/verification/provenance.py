"""Provenance validation: every ID a finding references must be real and
actually part of this investigation's scope -- not merely plausible.
"""

from specwatch.agent.tools.context import ToolContext
from specwatch.domain.models import FindingCandidate


def validate_provenance(
    candidate: FindingCandidate, changed_symbol_qualified_names: list[str], context: ToolContext
) -> list[str]:
    issues: list[str] = []

    for requirement_id in candidate.requirement_ids:
        if context.requirement_repo.get(requirement_id) is None:
            issues.append(f"unknown requirement_id: {requirement_id!r}")

    for symbol_id in candidate.changed_symbol_ids:
        if symbol_id not in changed_symbol_qualified_names:
            issues.append(f"changed_symbol_id not part of this investigation's scope: {symbol_id!r}")

    return issues
