"""Phase 6 acceptance: a harmless, requirement-unrelated code change must
not be routed to the Investigator Agent, exercised end to end on the real
fixture PRD + code repo (same pipeline `specwatch index` runs)."""

from pathlib import Path

from specwatch.code.symbol_index import build_symbol_index
from specwatch.domain.enums import SymbolChangeType
from specwatch.domain.models import ChangedSymbol
from specwatch.impact_filter import filter_changed_symbols, symbols_requiring_investigation
from specwatch.mapping.requirement_mapper import (
    build_symbol_bm25_index,
    build_test_bm25_index,
    candidate_symbols_for_requirement,
    candidate_tests_for_requirement,
)
from specwatch.specs.extractor import extract_requirements
from specwatch.storage.db import get_connection
from specwatch.storage.repositories import CandidateRepository
from specwatch.tests_index.index import build_test_index

CODE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_code_repo"
PRD_PATH = Path(__file__).parent.parent / "fixtures" / "sample_prd.md"


def _build_candidate_repo(tmp_path: Path) -> CandidateRepository:
    requirements = extract_requirements(PRD_PATH.read_text(), source_file="prd.md")
    symbol_index = build_symbol_index(CODE_ROOT)
    test_index = build_test_index(CODE_ROOT, symbol_index)
    symbol_bm25 = build_symbol_bm25_index(symbol_index)
    test_bm25 = build_test_bm25_index(test_index)

    conn = get_connection(tmp_path / "specwatch.db")
    candidate_repo = CandidateRepository(conn)
    for requirement in requirements:
        symbol_candidates = candidate_symbols_for_requirement(requirement, symbol_bm25)
        test_candidates = candidate_tests_for_requirement(
            requirement, symbol_candidates, test_index, test_bm25
        )
        candidate_repo.replace_symbol_candidates(requirement.id, symbol_candidates)
        candidate_repo.replace_test_candidates(requirement.id, test_candidates)
    return candidate_repo


def test_requirement_relevant_symbol_is_routed_to_investigation(tmp_path: Path) -> None:
    candidate_repo = _build_candidate_repo(tmp_path)
    changed = ChangedSymbol(
        qualified_name="app.services.invoice_service.InvoiceService.send",
        change_type=SymbolChangeType.MODIFIED,
    )

    decisions = filter_changed_symbols([changed], candidate_repo)

    assert len(symbols_requiring_investigation(decisions)) == 1
    assert decisions[0].candidate_requirements


def test_harmless_unrelated_change_is_not_routed_to_investigation(tmp_path: Path) -> None:
    """PostmarkClient.send_email shares no meaningful vocabulary with any
    of the three PRD requirements (see Phase 4's tests) -- this is the
    concrete "harmless unrelated code change" Phase 6's acceptance
    criterion requires never reach the Investigator Agent."""
    candidate_repo = _build_candidate_repo(tmp_path)
    changed = ChangedSymbol(
        qualified_name="app.providers.postmark_client.PostmarkClient.send_email",
        change_type=SymbolChangeType.MODIFIED,
    )

    decisions = filter_changed_symbols([changed], candidate_repo)

    assert symbols_requiring_investigation(decisions) == []
    assert decisions[0].should_investigate is False
