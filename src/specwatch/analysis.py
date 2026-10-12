"""End-to-end pipeline: diff -> impact filter -> investigation ->
verification -> deduplication. Ties Phases 1-9 into one callable --
this is what `specwatch analyze` runs.

Most PRs should exit after the impact filter with zero investigations:
that's the point of Phase 6's gate, not a shortcoming of this pipeline.
"""

import sqlite3
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from specwatch.agent.investigator import run_investigation
from specwatch.agent.tools.context import build_tool_context
from specwatch.domain.enums import SymbolKind
from specwatch.git.diff import changed_symbols
from specwatch.impact_filter import filter_changed_symbols, symbols_requiring_investigation
from specwatch.mapping.stale_spec import has_constant_value_mismatch
from specwatch.mapping.test_gap import has_test_evidence_gap
from specwatch.storage.repositories import CandidateRepository
from specwatch.verification.dedupe import deduplicate_verified_findings
from specwatch.verification.verifier import VerificationResult, verify_finding


def run_analysis(
    repo: Path,
    base: str,
    head: str,
    chat_model: BaseChatModel,
    conn: sqlite3.Connection,
    min_confidence: float,
    max_tool_calls: int,
    max_rounds: int,
) -> list[VerificationResult]:
    context = build_tool_context(repo, base, head, conn)
    candidate_repo = CandidateRepository(conn)

    diffs = changed_symbols(repo, base, head, repo)
    decisions = filter_changed_symbols(diffs, candidate_repo)
    to_investigate = symbols_requiring_investigation(decisions)

    results: list[VerificationResult] = []
    for decision in to_investigate:
        symbol_name = decision.changed_symbol.qualified_name
        test_gap_hints = {
            candidate.requirement_id: has_test_evidence_gap(
                context.requirement_repo.get(candidate.requirement_id),
                candidate_repo.test_candidates_for_requirement(candidate.requirement_id),
            )
            for candidate in decision.candidate_requirements
            if context.requirement_repo.get(candidate.requirement_id) is not None
        }

        changed_constant = decision.changed_symbol.head_symbol
        stale_spec_hints: dict[str, bool] = {}
        if changed_constant is not None and changed_constant.kind == SymbolKind.CONSTANT:
            stale_spec_hints = {
                candidate.requirement_id: has_constant_value_mismatch(
                    changed_constant, context.requirement_repo.get(candidate.requirement_id)
                )
                for candidate in decision.candidate_requirements
                if context.requirement_repo.get(candidate.requirement_id) is not None
            }

        changed_symbol = decision.changed_symbol.head_symbol or decision.changed_symbol.base_symbol
        diff_targets = [(changed_symbol.file, symbol_name)] if changed_symbol is not None else []

        finding, final_state = run_investigation(
            investigation_id=symbol_name,
            changed_symbol_qualified_names=[symbol_name],
            candidate_requirements=decision.candidate_requirements,
            chat_model=chat_model,
            context=context,
            max_tool_calls=max_tool_calls,
            max_rounds=max_rounds,
            test_gap_hints=test_gap_hints,
            stale_spec_hints=stale_spec_hints,
            diff_targets=diff_targets,
            prefetch=True,
        )
        result = verify_finding(
            finding,
            final_state["evidence_items"],
            [symbol_name],
            context,
            min_confidence,
        )
        results.append(result)

    return deduplicate_verified_findings(results)
