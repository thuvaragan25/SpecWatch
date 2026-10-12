"""Phase 9 acceptance: no FindingCandidate reaches "publish" without
surviving every deterministic check -- exercised against REAL evidence
produced by actually calling a Phase 7 tool, not a hand-typed string
that happens to match."""

import shutil
import subprocess
from pathlib import Path

import pytest

from specwatch.agent.state import EvidenceItem
from specwatch.agent.tools.code import inspect_symbol
from specwatch.agent.tools.context import ToolContext, build_tool_context
from specwatch.code.symbol_index import build_symbol_index
from specwatch.domain.enums import FindingVerdict
from specwatch.domain.models import Citation, FindingCandidate
from specwatch.mapping.requirement_mapper import (
    build_symbol_bm25_index,
    build_test_bm25_index,
    candidate_symbols_for_requirement,
    candidate_tests_for_requirement,
)
from specwatch.specs.extractor import extract_requirements
from specwatch.storage.db import get_connection
from specwatch.storage.repositories import CandidateRepository, RequirementRepository
from specwatch.tests_index.index import build_test_index
from specwatch.verification.verifier import verify_finding

FIXTURE_CODE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_code_repo"
FIXTURE_PRD = Path(__file__).parent.parent / "fixtures" / "sample_prd.md"

INVOICE_SEND = "app.services.invoice_service.InvoiceService.send"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def tool_context(tmp_path: Path) -> ToolContext:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_CODE_ROOT, repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "head")

    requirements = extract_requirements(FIXTURE_PRD.read_text(), source_file="prd.md")
    conn = get_connection(tmp_path / "specwatch.db")
    RequirementRepository(conn).save_all(requirements)

    symbol_index = build_symbol_index(repo)
    test_index = build_test_index(repo, symbol_index)
    symbol_bm25 = build_symbol_bm25_index(symbol_index)
    test_bm25 = build_test_bm25_index(test_index)
    candidate_repo = CandidateRepository(conn)
    for requirement in requirements:
        symbol_candidates = candidate_symbols_for_requirement(requirement, symbol_bm25)
        test_candidates = candidate_tests_for_requirement(
            requirement, symbol_candidates, test_index, test_bm25
        )
        candidate_repo.replace_symbol_candidates(requirement.id, symbol_candidates)
        candidate_repo.replace_test_candidates(requirement.id, test_candidates)

    return build_tool_context(repo, base=base_sha, head="HEAD", conn=conn)


def _approval_requirement_id(tool_context: ToolContext) -> str:
    return next(r.id for r in tool_context.requirement_repo.list() if r.title == "Invoice Approval")


def _real_evidence_and_citation(tool_context: ToolContext) -> tuple[EvidenceItem, Citation]:
    """Actually call inspect_symbol and build a citation from its real
    result, quoting a real line from the real file -- not a hand-typed
    string that happens to match."""
    result = inspect_symbol(tool_context, INVOICE_SEND, revision="head")
    assert result is not None
    evidence = EvidenceItem(
        id="ev-1",
        tool_name="inspect_symbol",
        tool_args={"qualified_name": INVOICE_SEND, "revision": "head"},
        round=1,
        content=result.model_dump_json(),
    )
    source = tool_context.read_source("head", result.file)
    assert source is not None
    quoted_line = source.splitlines()[result.source.line_start - 1]
    citation = Citation(
        evidence_id="ev-1",
        file=result.file,
        line_start=result.source.line_start,
        line_end=result.source.line_start,
        quote=quoted_line.strip(),
    )
    return evidence, citation


def test_well_formed_finding_with_real_evidence_publishes(tool_context: ToolContext) -> None:
    evidence, citation = _real_evidence_and_citation(tool_context)
    req_id = _approval_requirement_id(tool_context)
    finding = FindingCandidate(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        requirement_ids=[req_id],
        changed_symbol_ids=[INVOICE_SEND],
        summary="Approval guard appears to be missing.",
        reasoning="Inspected InvoiceService.send and found no approval check.",
        citations=[citation],
        model_confidence=0.9,
    )

    result = verify_finding(finding, [evidence], [INVOICE_SEND], tool_context, min_confidence=0.1)

    assert result.decision == "publish"
    assert result.reasons == []


def test_no_issue_verdict_always_abstains_regardless_of_citations(tool_context: ToolContext) -> None:
    evidence, citation = _real_evidence_and_citation(tool_context)
    finding = FindingCandidate(
        verdict=FindingVerdict.NO_ISSUE,
        citations=[citation],
        summary="No issue.",
        reasoning="Checked and found nothing wrong.",
        model_confidence=0.99,
    )

    result = verify_finding(finding, [evidence], [INVOICE_SEND], tool_context, min_confidence=0.0)

    assert result.decision == "abstain"


def test_fabricated_evidence_id_is_suppressed(tool_context: ToolContext) -> None:
    _evidence, citation = _real_evidence_and_citation(tool_context)
    bad_citation = citation.model_copy(update={"evidence_id": "ev-does-not-exist"})
    finding = FindingCandidate(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        changed_symbol_ids=[INVOICE_SEND],
        summary="s",
        reasoning="r",
        citations=[bad_citation],
        model_confidence=0.9,
    )

    result = verify_finding(finding, [], [INVOICE_SEND], tool_context, min_confidence=0.0)

    assert result.decision == "suppress"
    assert any("was not retrieved" in reason for reason in result.reasons)


def test_wrong_file_in_citation_is_suppressed(tool_context: ToolContext) -> None:
    evidence, citation = _real_evidence_and_citation(tool_context)
    bad_citation = citation.model_copy(update={"file": "app/providers/postmark_client.py"})
    finding = FindingCandidate(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        changed_symbol_ids=[INVOICE_SEND],
        summary="s",
        reasoning="r",
        citations=[bad_citation],
        model_confidence=0.9,
    )

    result = verify_finding(finding, [evidence], [INVOICE_SEND], tool_context, min_confidence=0.0)

    assert result.decision == "suppress"
    assert any("does not appear in evidence" in reason for reason in result.reasons)


def test_fabricated_quote_is_suppressed(tool_context: ToolContext) -> None:
    evidence, citation = _real_evidence_and_citation(tool_context)
    bad_citation = citation.model_copy(update={"quote": "this text does not exist in the source"})
    finding = FindingCandidate(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        changed_symbol_ids=[INVOICE_SEND],
        summary="s",
        reasoning="r",
        citations=[bad_citation],
        model_confidence=0.9,
    )

    result = verify_finding(finding, [evidence], [INVOICE_SEND], tool_context, min_confidence=0.0)

    assert result.decision == "suppress"
    assert any("not found in the cited line range" in reason for reason in result.reasons)


def test_unknown_requirement_id_is_suppressed(tool_context: ToolContext) -> None:
    evidence, citation = _real_evidence_and_citation(tool_context)
    finding = FindingCandidate(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        requirement_ids=["REQ-NOPE00"],
        changed_symbol_ids=[INVOICE_SEND],
        summary="s",
        reasoning="r",
        citations=[citation],
        model_confidence=0.9,
    )

    result = verify_finding(finding, [evidence], [INVOICE_SEND], tool_context, min_confidence=0.0)

    assert result.decision == "suppress"
    assert any("unknown requirement_id" in reason for reason in result.reasons)


def test_changed_symbol_out_of_scope_is_suppressed(tool_context: ToolContext) -> None:
    evidence, citation = _real_evidence_and_citation(tool_context)
    finding = FindingCandidate(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        changed_symbol_ids=["app.some.other.symbol"],
        summary="s",
        reasoning="r",
        citations=[citation],
        model_confidence=0.9,
    )

    result = verify_finding(finding, [evidence], [INVOICE_SEND], tool_context, min_confidence=0.0)

    assert result.decision == "suppress"
    assert any("not part of this investigation" in reason for reason in result.reasons)


def test_no_citations_on_actionable_verdict_is_suppressed(tool_context: ToolContext) -> None:
    finding = FindingCandidate(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        changed_symbol_ids=[INVOICE_SEND],
        summary="s",
        reasoning="r",
        citations=[],
        model_confidence=0.9,
    )

    result = verify_finding(finding, [], [INVOICE_SEND], tool_context, min_confidence=0.0)

    assert result.decision == "suppress"
    assert any("no citations" in reason for reason in result.reasons)


def test_low_confidence_is_suppressed_even_with_valid_citations(tool_context: ToolContext) -> None:
    evidence, citation = _real_evidence_and_citation(tool_context)
    finding = FindingCandidate(
        verdict=FindingVerdict.SPEC_VIOLATION_LIKELY,
        changed_symbol_ids=[INVOICE_SEND],
        summary="s",
        reasoning="r",
        citations=[citation],
        model_confidence=0.1,
    )

    result = verify_finding(finding, [evidence], [INVOICE_SEND], tool_context, min_confidence=0.95)

    assert result.decision == "suppress"
    assert any("below threshold" in reason for reason in result.reasons)
