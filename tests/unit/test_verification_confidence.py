from pathlib import Path

from specwatch.agent.state import EvidenceItem
from specwatch.agent.tools.context import ToolContext
from specwatch.code.symbol_index import SymbolIndex
from specwatch.domain.enums import CandidateMethod, FindingVerdict
from specwatch.domain.models import Citation, FindingCandidate, RequirementCandidate
from specwatch.storage.db import get_connection
from specwatch.storage.repositories import CandidateRepository, RequirementRepository
from specwatch.tests_index.index import PytestIndex
from specwatch.verification.confidence import compute_confidence


def _minimal_context(tmp_path: Path) -> ToolContext:
    conn = get_connection(tmp_path / "specwatch.db")
    return ToolContext(
        repo=tmp_path,
        base="base",
        head="head",
        base_symbol_index=SymbolIndex(),
        head_symbol_index=SymbolIndex(),
        head_test_index=PytestIndex(),
        requirement_repo=RequirementRepository(conn),
        candidate_repo=CandidateRepository(conn),
    )


def _finding(**overrides) -> FindingCandidate:
    defaults = dict(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        requirement_ids=["REQ-1"],
        changed_symbol_ids=["pkg.Foo.bar"],
        summary="s",
        reasoning="r",
        citations=[],
        model_confidence=0.5,
    )
    defaults.update(overrides)
    return FindingCandidate(**defaults)


def test_confidence_increases_with_more_citations(tmp_path: Path) -> None:
    context = _minimal_context(tmp_path)
    low = compute_confidence(_finding(citations=[]), [], context)
    high = compute_confidence(
        _finding(
            citations=[
                Citation(evidence_id="ev-1", file="a.py", line_start=1, line_end=1, quote="x"),
                Citation(evidence_id="ev-2", file="a.py", line_start=1, line_end=1, quote="y"),
            ]
        ),
        [],
        context,
    )
    assert high > low


def test_confidence_increases_with_requirement_mapping_strength(tmp_path: Path) -> None:
    context = _minimal_context(tmp_path)
    context.candidate_repo.replace_symbol_candidates(
        "REQ-1",
        [
            RequirementCandidate(
                requirement_id="REQ-1", symbol_qualified_name="pkg.Foo.bar", score=5.0, method=CandidateMethod.LEXICAL
            )
        ],
    )
    with_mapping = compute_confidence(_finding(), [], context)
    without_mapping = compute_confidence(_finding(requirement_ids=["REQ-UNMAPPED"]), [], context)
    assert with_mapping > without_mapping


def test_confidence_increases_with_evidence_diversity(tmp_path: Path) -> None:
    context = _minimal_context(tmp_path)
    few_tools = [EvidenceItem(id="ev-1", tool_name="search_code", tool_args={}, round=1, content="{}")]
    many_tools = [
        EvidenceItem(id="ev-1", tool_name="search_code", tool_args={}, round=1, content="{}"),
        EvidenceItem(id="ev-2", tool_name="inspect_symbol", tool_args={}, round=1, content="{}"),
        EvidenceItem(id="ev-3", tool_name="inspect_callers", tool_args={}, round=1, content="{}"),
    ]
    assert compute_confidence(_finding(), many_tools, context) > compute_confidence(_finding(), few_tools, context)


def test_confidence_is_clamped_to_unit_interval(tmp_path: Path) -> None:
    context = _minimal_context(tmp_path)
    citations = [Citation(evidence_id="e", file="a.py", line_start=1, line_end=1, quote="x")] * 5
    score = compute_confidence(_finding(model_confidence=1.0, citations=citations), [], context)
    assert 0.0 <= score <= 1.0


def test_confidence_with_no_signals_is_low(tmp_path: Path) -> None:
    context = _minimal_context(tmp_path)
    score = compute_confidence(_finding(model_confidence=0.0, citations=[]), [], context)
    assert score < 0.1
