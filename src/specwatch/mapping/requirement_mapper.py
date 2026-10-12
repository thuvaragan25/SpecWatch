"""Requirement <-> code and requirement <-> test candidate generation.

Deterministic candidate generation first (plan.md §17): lexical (BM25)
ranking for requirement<->code and requirement<->test, plus the higher-
confidence call-graph signal already computed in Phase 3
(PytestIndex.tests_referencing) for requirement<->test. LLM ranking of a
small candidate set is a later addition, only if evaluation shows lexical
ranking is insufficient -- not built in V1.
"""

from pathlib import Path

from specwatch.code.symbol_index import SymbolIndex
from specwatch.domain.enums import CandidateMethod, SymbolKind
from specwatch.domain.models import CodeSymbol, Requirement, RequirementCandidate, RequirementTestCandidate, TestSymbol
from specwatch.mapping.candidate_generator import BM25Index, Document
from specwatch.tests_index.index import PytestIndex
from specwatch.tests_index.pytest_parser import is_test_file

_SEARCHABLE_SYMBOL_KINDS = {
    SymbolKind.CLASS,
    SymbolKind.FUNCTION,
    SymbolKind.METHOD,
    SymbolKind.CONSTANT,
}


def build_symbol_bm25_index(symbol_index: SymbolIndex) -> BM25Index:
    """Implementation-symbol candidates only -- test functions are excluded
    here since they're surfaced through the dedicated test-candidate path
    instead, so they don't double up as noise in "candidate code symbols"."""
    documents = [
        Document(id=symbol.qualified_name, text=_symbol_document_text(symbol))
        for symbol in symbol_index.symbols.values()
        if symbol.kind in _SEARCHABLE_SYMBOL_KINDS and not is_test_file(Path(symbol.file).name)
    ]
    return BM25Index(documents)


_EXPANSION_SEED_COUNT = 5
_EXPANSION_SCORE_FACTOR = 0.5


def expand_candidates_via_callers(
    candidates: list[RequirementCandidate],
    symbol_index: SymbolIndex,
    seed_count: int = _EXPANSION_SEED_COUNT,
    limit: int = 8,
) -> list[RequirementCandidate]:
    """Add the code that *uses* the top lexical candidates.

    Specs name the concepts a requirement is about (an exception, a
    constant, a helper), but the code that actually enforces the
    requirement often only references them -- e.g. ``_validate_exp`` raises
    ``ExpiredSignatureError`` -- and lexically shares nothing with the spec
    text. Resolved call edges (which include instantiation, so ``raise
    X(...)``) lead from the named concept to its enforcer. Expansion is
    one hop, seeded from the strongest lexical matches, with a decayed
    score so lexical matches still rank first.
    """
    if not candidates:
        return candidates

    known = {c.symbol_qualified_name for c in candidates}
    expanded: dict[str, RequirementCandidate] = {}
    for seed in sorted(candidates, key=lambda c: c.score, reverse=True)[:seed_count]:
        for edge in symbol_index.callers_of(seed.symbol_qualified_name):
            caller = symbol_index.get(edge.caller_qualified_name)
            if (
                caller is None
                or caller.qualified_name in known
                or caller.kind not in _SEARCHABLE_SYMBOL_KINDS
                or is_test_file(Path(caller.file).name)
            ):
                continue
            score = seed.score * _EXPANSION_SCORE_FACTOR
            existing = expanded.get(caller.qualified_name)
            if existing is None or score > existing.score:
                expanded[caller.qualified_name] = RequirementCandidate(
                    requirement_id=seed.requirement_id,
                    symbol_qualified_name=caller.qualified_name,
                    score=score,
                    method=CandidateMethod.STATIC_ANALYSIS,
                )

    extra = sorted(expanded.values(), key=lambda c: c.score, reverse=True)[:limit]
    return [*candidates, *extra]


def build_test_bm25_index(test_index: PytestIndex) -> BM25Index:
    documents = [
        Document(id=test.qualified_name, text=_test_document_text(test))
        for test in test_index.list()
    ]
    return BM25Index(documents)


def candidate_symbols_for_requirement(
    requirement: Requirement, symbol_bm25: BM25Index, limit: int = 8
) -> list[RequirementCandidate]:
    query = f"{requirement.title} {requirement.statement}"
    return [
        RequirementCandidate(
            requirement_id=requirement.id,
            symbol_qualified_name=symbol_qualified_name,
            score=score,
            method=CandidateMethod.LEXICAL,
        )
        for symbol_qualified_name, score in symbol_bm25.search(query, limit=limit)
    ]


def candidate_tests_for_requirement(
    requirement: Requirement,
    symbol_candidates: list[RequirementCandidate],
    test_index: PytestIndex,
    test_bm25: BM25Index,
    limit: int = 8,
) -> list[RequirementTestCandidate]:
    """Prefer tests the call graph confirms exercise a candidate symbol
    (STATIC_ANALYSIS); fall back to direct lexical match against the
    requirement text (LEXICAL) for requirements without a clean symbol
    match."""
    candidates: dict[str, RequirementTestCandidate] = {}

    for symbol_candidate in symbol_candidates:
        for test in test_index.tests_referencing(symbol_candidate.symbol_qualified_name):
            candidates[test.qualified_name] = RequirementTestCandidate(
                requirement_id=requirement.id,
                test_qualified_name=test.qualified_name,
                score=symbol_candidate.score,
                method=CandidateMethod.STATIC_ANALYSIS,
            )

    query = f"{requirement.title} {requirement.statement}"
    for test_qualified_name, score in test_bm25.search(query, limit=limit):
        candidates.setdefault(
            test_qualified_name,
            RequirementTestCandidate(
                requirement_id=requirement.id,
                test_qualified_name=test_qualified_name,
                score=score,
                method=CandidateMethod.LEXICAL,
            ),
        )

    ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
    return ranked[:limit]


def _symbol_document_text(symbol: CodeSymbol) -> str:
    parts = [symbol.qualified_name, symbol.file]
    if symbol.docstring:
        parts.append(symbol.docstring)
    return " ".join(parts)


def _test_document_text(test: TestSymbol) -> str:
    parts = [test.qualified_name, test.file]
    if test.docstring:
        parts.append(test.docstring)
    return " ".join(parts)
