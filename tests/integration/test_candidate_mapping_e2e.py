"""Phase 4 acceptance: requirement -> code and requirement -> test
candidate generation, using only deterministic lexical/call-graph
signals, exercised end to end on the real fixture PRD + code repo."""

from pathlib import Path

from specwatch.code.symbol_index import build_symbol_index
from specwatch.domain.enums import CandidateMethod
from specwatch.mapping.requirement_mapper import (
    build_symbol_bm25_index,
    build_test_bm25_index,
    candidate_symbols_for_requirement,
    candidate_tests_for_requirement,
)
from specwatch.specs.extractor import extract_requirements
from specwatch.tests_index.index import build_test_index

CODE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_code_repo"
PRD_PATH = Path(__file__).parent.parent / "fixtures" / "sample_prd.md"


def _invoice_approval_requirement():
    requirements = extract_requirements(PRD_PATH.read_text(), source_file="prd.md")
    return next(r for r in requirements if r.title == "Invoice Approval")


def test_invoice_approval_requirement_ranks_invoice_service_above_unrelated_symbol() -> None:
    approval = _invoice_approval_requirement()
    symbol_index = build_symbol_index(CODE_ROOT)
    symbol_bm25 = build_symbol_bm25_index(symbol_index)

    candidates = candidate_symbols_for_requirement(approval, symbol_bm25)
    candidate_names = [c.symbol_qualified_name for c in candidates]

    assert "app.services.invoice_service.InvoiceService" in candidate_names
    assert "app.providers.postmark_client.PostmarkClient" not in candidate_names


def test_invoice_approval_requirement_finds_its_test_via_call_graph() -> None:
    approval = _invoice_approval_requirement()
    symbol_index = build_symbol_index(CODE_ROOT)
    test_index = build_test_index(CODE_ROOT, symbol_index)
    symbol_bm25 = build_symbol_bm25_index(symbol_index)
    test_bm25 = build_test_bm25_index(test_index)

    symbol_candidates = candidate_symbols_for_requirement(approval, symbol_bm25)
    test_candidates = candidate_tests_for_requirement(
        approval, symbol_candidates, test_index, test_bm25
    )

    matched = next(
        c
        for c in test_candidates
        if c.test_qualified_name
        == "tests.test_invoice_service.test_send_invoice_delivers_via_client"
    )
    assert matched.method == CandidateMethod.STATIC_ANALYSIS
