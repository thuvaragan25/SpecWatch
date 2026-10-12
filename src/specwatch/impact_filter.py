"""Deterministic impact filter: decide which changed symbols warrant
Investigator Agent attention.

Per plan.md §2/§11.5: most PRs touch nothing requirement-relevant, and
the agent must never be invoked for those -- this is the gate that keeps
agent invocations rare, cheap, and meaningful. A changed symbol is
escalated to investigation only if a requirement (or architecture-rule)
candidate link already exists for it (Phase 4's candidate tables).

A narrow deterministic fast-path for simple literal-value mismatches
(e.g. a numeric constant compared directly against a spec'd number, per
plan.md §2's TTL example) is intentionally NOT built here. It's a
targeted future optimization once real cases justify a dedicated code
path -- not something this phase's acceptance criterion ("a harmless
unrelated code change should not invoke the Investigator Agent") or
Phase 10's actual test cases require. V1 lets the agent reason about a
changed constant directly, the same as any other candidate-linked
symbol.
"""

from dataclasses import dataclass, field

from specwatch.domain.enums import SymbolKind
from specwatch.domain.models import ChangedSymbol, RequirementCandidate
from specwatch.storage.repositories import CandidateRepository


@dataclass(frozen=True)
class ImpactDecision:
    """Whether one changed symbol has a requirement relationship worth
    investigating, and which candidates justify that."""

    changed_symbol: ChangedSymbol
    should_investigate: bool
    candidate_requirements: list[RequirementCandidate] = field(default_factory=list)


def filter_changed_symbols(
    changed_symbols: list[ChangedSymbol], candidate_repo: CandidateRepository
) -> list[ImpactDecision]:
    """Decide, independently for each changed symbol, whether it has a
    candidate requirement relationship worth investigating."""
    changed_names = {changed.qualified_name for changed in changed_symbols}
    decisions: list[ImpactDecision] = []
    for changed in changed_symbols:
        candidates = candidate_repo.requirements_for_symbol(changed.qualified_name)
        investigate = bool(candidates) and not _is_container_of_other_changes(changed, changed_names)
        decisions.append(
            ImpactDecision(
                changed_symbol=changed,
                should_investigate=investigate,
                candidate_requirements=candidates,
            )
        )
    return decisions


def _is_container_of_other_changes(changed: ChangedSymbol, changed_names: set[str]) -> bool:
    """A class/module's own body hash changes whenever any member does, so
    it shows up as "modified" alongside the member that actually changed.
    Investigating both is duplicate work -- the member carries the signal."""
    symbol = changed.head_symbol or changed.base_symbol
    if symbol is None or symbol.kind not in (SymbolKind.CLASS, SymbolKind.MODULE):
        return False
    prefix = f"{changed.qualified_name}."
    return any(name.startswith(prefix) for name in changed_names)


def symbols_requiring_investigation(decisions: list[ImpactDecision]) -> list[ImpactDecision]:
    return [decision for decision in decisions if decision.should_investigate]
