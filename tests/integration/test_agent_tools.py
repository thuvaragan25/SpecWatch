"""Phase 7 acceptance: every agent tool's normal path, missing-target/
invalid-ID behavior, result-size bounds, and line-range correctness --
built on one real temporary git repository shared across all tools, so
revision-awareness (base vs head) is exercised concretely rather than
mocked.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from specwatch.agent.tools.code import (
    inspect_callees,
    inspect_callers,
    inspect_diff,
    inspect_symbol,
    search_code,
)
from specwatch.agent.tools.context import MAX_CALL_RESULTS, MAX_COMMIT_HISTORY_LIMIT, ToolContext, build_tool_context
from specwatch.agent.tools.git import inspect_git_history
from specwatch.agent.tools.requirements import inspect_requirement, search_requirements
from specwatch.agent.tools.tests import inspect_test, search_tests
from specwatch.code.symbol_index import build_symbol_index
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

FIXTURE_CODE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_code_repo"
FIXTURE_PRD = Path(__file__).parent.parent / "fixtures" / "sample_prd.md"

_HEAD_INVOICE_SERVICE = '''"""Invoice sending service."""

from app.services.delivery_service import InvoiceDeliveryService


class InvoiceService:
    """Coordinates invoice approval and delivery."""

    def __init__(self, delivery: InvoiceDeliveryService) -> None:
        self.delivery = delivery

    def send(self, invoice_id: str) -> None:
        """Send an approved invoice, now logging first."""
        print(f"sending {invoice_id}")
        self.delivery.deliver(invoice_id)
'''


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

    (repo / "app" / "services" / "invoice_service.py").write_text(_HEAD_INVOICE_SERVICE)
    _git(repo, "commit", "-q", "-am", "head: log before delivering")

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


INVOICE_SEND = "app.services.invoice_service.InvoiceService.send"
DELIVER = "app.services.delivery_service.InvoiceDeliveryService.deliver"
POSTMARK_SEND = "app.providers.postmark_client.PostmarkClient.send_email"
APPROVAL_REQ_TITLE = "Invoice Approval"


def _approval_requirement_id(tool_context: ToolContext) -> str:
    return next(
        r.id for r in tool_context.requirement_repo.list() if r.title == APPROVAL_REQ_TITLE
    )


# --- search_requirements / inspect_requirement -----------------------------


def test_search_requirements_finds_relevant_requirement(tool_context: ToolContext) -> None:
    hits = search_requirements(tool_context, "invoice approval")
    assert any(h.title == APPROVAL_REQ_TITLE for h in hits)


def test_search_requirements_respects_limit(tool_context: ToolContext) -> None:
    hits = search_requirements(tool_context, "invoice approval", limit=1)
    assert len(hits) <= 1


def test_inspect_requirement_normal_path(tool_context: ToolContext) -> None:
    req_id = _approval_requirement_id(tool_context)
    detail = inspect_requirement(tool_context, req_id)
    assert detail is not None
    assert "approved" in detail.statement


def test_inspect_requirement_invalid_id_returns_none(tool_context: ToolContext) -> None:
    assert inspect_requirement(tool_context, "REQ-NOPE00") is None


# --- search_code / inspect_symbol ------------------------------------------


def test_search_code_finds_relevant_symbol(tool_context: ToolContext) -> None:
    hits = search_code(tool_context, "invoice approval")
    assert any(h.qualified_name == "app.services.invoice_service.InvoiceService" for h in hits)


def test_search_code_excludes_test_files(tool_context: ToolContext) -> None:
    hits = search_code(tool_context, "invoice approval")
    assert not any("test" in h.qualified_name.split(".")[0] for h in hits)
    assert not any(h.file.startswith("tests/") for h in hits)


def test_inspect_symbol_normal_path_at_head(tool_context: ToolContext) -> None:
    detail = inspect_symbol(tool_context, INVOICE_SEND, revision="head")
    assert detail is not None
    assert "print" in detail.source_snippet
    assert detail.callee_count >= 2  # print(...) and self.delivery.deliver(...)


def test_inspect_symbol_is_revision_aware(tool_context: ToolContext) -> None:
    """The same qualified name returns different source on each side --
    concrete proof base/head aren't accidentally sharing one index."""
    base_detail = inspect_symbol(tool_context, INVOICE_SEND, revision="base")
    head_detail = inspect_symbol(tool_context, INVOICE_SEND, revision="head")
    assert base_detail is not None and head_detail is not None
    assert "print" not in base_detail.source_snippet
    assert "print" in head_detail.source_snippet


def test_inspect_symbol_missing_target_returns_none(tool_context: ToolContext) -> None:
    assert inspect_symbol(tool_context, "app.does.not.exist", revision="head") is None


def test_inspect_symbol_line_range_is_correct(tool_context: ToolContext) -> None:
    detail = inspect_symbol(tool_context, INVOICE_SEND, revision="head")
    assert detail is not None
    line_count = detail.source.line_end - detail.source.line_start + 1
    assert len(detail.source_snippet.splitlines()) == line_count


# --- inspect_callers / inspect_callees --------------------------------------


def test_inspect_callers_normal_path(tool_context: ToolContext) -> None:
    callers = inspect_callers(tool_context, DELIVER, revision="head")
    assert any(c.caller_qualified_name == INVOICE_SEND for c in callers)


def test_inspect_callers_missing_target_returns_empty(tool_context: ToolContext) -> None:
    assert inspect_callers(tool_context, "app.nothing.calls.this", revision="head") == []


def test_inspect_callers_depth_is_capped(tool_context: ToolContext) -> None:
    callers = inspect_callers(tool_context, DELIVER, revision="head", depth=999)
    assert len(callers) <= MAX_CALL_RESULTS


def test_inspect_callees_includes_unresolved_calls(tool_context: ToolContext) -> None:
    """print(...) is a builtin -- an honest static-analysis limit -- and
    must be reported as unresolved evidence, not silently dropped."""
    callees = inspect_callees(tool_context, INVOICE_SEND, revision="head")
    resolved_refs = {c.callee_reference: c.resolved for c in callees}
    assert resolved_refs.get("print") is False
    assert resolved_refs.get("self.delivery.deliver") is True


def test_inspect_callees_result_size_is_bounded(tool_context: ToolContext) -> None:
    callees = inspect_callees(tool_context, INVOICE_SEND, revision="head", depth=999)
    assert len(callees) <= MAX_CALL_RESULTS


# --- inspect_diff ------------------------------------------------------------


def test_inspect_diff_symbol_shows_the_added_line(tool_context: ToolContext) -> None:
    result = inspect_diff(tool_context, file="app/services/invoice_service.py", symbol=INVOICE_SEND)
    assert result is not None
    assert "print" not in (result.before_source or "")
    assert "print" in (result.after_source or "")
    assert any(line.startswith("+") and "print" in line for line in result.diff.splitlines())


def test_inspect_diff_file_level(tool_context: ToolContext) -> None:
    result = inspect_diff(tool_context, file="app/services/invoice_service.py")
    assert result is not None
    assert "print" in result.diff


def test_inspect_diff_unchanged_symbol_has_empty_diff(tool_context: ToolContext) -> None:
    result = inspect_diff(
        tool_context, file="app/providers/postmark_client.py", symbol=POSTMARK_SEND
    )
    assert result is not None
    assert result.diff == ""
    assert result.before_source == result.after_source


def test_inspect_diff_missing_symbol_returns_none(tool_context: ToolContext) -> None:
    result = inspect_diff(tool_context, file="app/services/invoice_service.py", symbol="app.nope")
    assert result is None


# --- search_tests / inspect_test --------------------------------------------


def test_search_tests_by_symbol_uses_call_graph(tool_context: ToolContext) -> None:
    hits = search_tests(
        tool_context, symbol="app.services.invoice_service.InvoiceService"
    )
    assert any("test_send_invoice_delivers_via_client" in h.qualified_name for h in hits)


def test_search_tests_by_requirement_id(tool_context: ToolContext) -> None:
    req_id = _approval_requirement_id(tool_context)
    hits = search_tests(tool_context, requirement_id=req_id)
    assert any("test_send_invoice_delivers_via_client" in h.qualified_name for h in hits)


def test_search_tests_by_query(tool_context: ToolContext) -> None:
    # "delivers" is the token that discriminates: it's unique to
    # test_send_invoice_delivers_via_client among the fixture's three
    # tests, giving BM25 a real (non-degenerate) positive-IDF signal.
    hits = search_tests(tool_context, query="invoice delivers")
    assert any("test_send_invoice_delivers_via_client" in h.qualified_name for h in hits)


def test_search_tests_with_no_signals_returns_empty(tool_context: ToolContext) -> None:
    assert search_tests(tool_context) == []


def test_inspect_test_normal_path(tool_context: ToolContext) -> None:
    detail = inspect_test(
        tool_context, "tests.test_invoice_service.test_send_invoice_delivers_via_client"
    )
    assert detail is not None
    assert detail.fixtures == ["capsys"]
    assert detail.assertions


def test_inspect_test_missing_target_returns_none(tool_context: ToolContext) -> None:
    assert inspect_test(tool_context, "tests.test_invoice_service.test_nonexistent") is None


# --- inspect_git_history -----------------------------------------------------


def test_inspect_git_history_by_file(tool_context: ToolContext) -> None:
    commits = inspect_git_history(tool_context, file="app/services/invoice_service.py")
    assert len(commits) == 2
    assert any("head" in c.message for c in commits)
    assert all("invoice_service.py" in c.stat for c in commits)


def test_inspect_git_history_by_symbol_resolves_its_file(tool_context: ToolContext) -> None:
    commits = inspect_git_history(tool_context, symbol=INVOICE_SEND)
    assert len(commits) == 2


def test_inspect_git_history_limit_is_capped(tool_context: ToolContext) -> None:
    commits = inspect_git_history(tool_context, file="app/services/invoice_service.py", limit=999)
    assert len(commits) <= MAX_COMMIT_HISTORY_LIMIT


def test_inspect_git_history_missing_target_returns_empty(tool_context: ToolContext) -> None:
    assert inspect_git_history(tool_context, symbol="app.does.not.exist") == []


def test_inspect_diff_symbol_reports_changed_lines_with_real_file_line_numbers(tool_context: ToolContext) -> None:
    result = inspect_diff(tool_context, file="app/services/invoice_service.py", symbol=INVOICE_SEND)

    assert result is not None
    head_lines = tool_context.read_source("head", "app/services/invoice_service.py").splitlines()
    assert result.added_or_changed_lines, "expected the symbol's changed lines to be listed"
    for ref in result.added_or_changed_lines:
        assert head_lines[ref.line - 1] == ref.text  # real, verbatim, 1-indexed file line
        assert not ref.text.startswith(("+", "-"))
