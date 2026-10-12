"""Phase 10 acceptance: the flagship spec-to-code drift scenarios from
plan.md §2 / Phase 10, run through the REAL end-to-end pipeline
(run_analysis: diff -> impact filter -> investigate -> verify -> dedup).

No live API key is available, so each scenario's primary investigated
symbol is driven by a scripted fake chat model whose tool calls and
final verdict represent what a well-reasoning agent following plan.md's
own worked examples (§2, §18) WOULD do -- actively looking for whether
enforcement moved elsewhere before concluding it's gone. This proves the
pipeline's WIRING is correct (a well-reasoning agent's conclusion
correctly becomes a published finding, a suppressed one, or an
abstention); it does not prove a real model reasons this well on its
own, which needs a live API key and belongs in the opt-in eval track
per plan.md's testing rules.

Several symbols besides the primary one are incidentally flagged for
investigation too (e.g. a container class whose body_hash changes
whenever any of its methods does -- see Phase 5's own docstring on this).
Each scenario's ScriptedInvestigatorFake gives those a generic
"insufficient_evidence" default so they can't accidentally get published
and corrupt the assertions, without needing to predict or script every
one of them individually.
"""

import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from fake_chat_models import (
    ScriptedInvestigatorFake,
    default_abstain_script,
    submit_finding_call,
    tool_call,
)

from specwatch.agent.tools.code import inspect_symbol
from specwatch.agent.tools.context import build_tool_context
from specwatch.analysis import run_analysis
from specwatch.code.symbol_index import build_symbol_index
from specwatch.domain.enums import FindingVerdict
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

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "auth_scenario_repo"
GET_DOCUMENTS = "app.services.document_service.DocumentService.get_documents"

_tool_call = tool_call
_submit_finding_call = submit_finding_call
_default_abstain_script = default_abstain_script


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _setup(tmp_path: Path, apply_head_edit) -> tuple[Path, str, sqlite3.Connection]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_ROOT, repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    apply_head_edit(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head")

    conn = get_connection(tmp_path / "specwatch.db")
    requirements = extract_requirements((repo / "docs" / "prd.md").read_text(), source_file="docs/prd.md")
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

    return repo, base_sha, conn


def _requirement_id(conn: sqlite3.Connection) -> str:
    return next(r.id for r in RequirementRepository(conn).list() if r.title == "Project Document Access")


# --- scenario head-state edits -----------------------------------------------


def _apply_scenario_a_removed_check(repo: Path) -> None:
    """The local membership check is removed. Nothing replaces it anywhere."""
    (repo / "app/services/document_service.py").write_text(
        '"""Serves project documents to authorized members."""\n\n\n'
        "class DocumentService:\n"
        '    """Retrieves documents for a project."""\n\n'
        "    def get_documents(self, user_id: str, project_id: str) -> list[str]:\n"
        '        """Return a project\'s documents."""\n'
        "        return self._fetch(project_id)\n\n"
        "    def _fetch(self, project_id: str) -> list[str]:\n"
        '        return [f"{project_id}/doc1.txt", f"{project_id}/doc2.txt"]\n'
    )


def _apply_scenario_b_moved_to_middleware(repo: Path) -> None:
    """The local check is removed from the service, but equivalent
    enforcement is added at the route/middleware layer instead."""
    (repo / "app/services/document_service.py").write_text(
        '"""Serves project documents to authorized members."""\n\n\n'
        "class DocumentService:\n"
        '    """Retrieves documents for a project."""\n\n'
        "    def get_documents(self, user_id: str, project_id: str) -> list[str]:\n"
        '        """Return a project\'s documents."""\n'
        "        return self._fetch(project_id)\n\n"
        "    def _fetch(self, project_id: str) -> list[str]:\n"
        '        return [f"{project_id}/doc1.txt", f"{project_id}/doc2.txt"]\n'
    )
    (repo / "app/middleware").mkdir(exist_ok=True)
    (repo / "app/middleware/__init__.py").write_text("")
    (repo / "app/middleware/auth_middleware.py").write_text(
        '"""Route-level authorization middleware."""\n\n'
        "from app.auth.membership import MembershipChecker\n\n\n"
        "class AuthMiddleware:\n"
        '    """Enforces project membership before a request reaches a handler."""\n\n'
        "    def __init__(self, membership: MembershipChecker) -> None:\n"
        "        self.membership = membership\n\n"
        "    def enforce(self, user_id: str, project_id: str) -> None:\n"
        '        """Raise PermissionError if the user is not a project member."""\n'
        "        if not self.membership.is_member(user_id, project_id):\n"
        '            raise PermissionError("not a project member")\n'
    )
    (repo / "app/routes").mkdir(exist_ok=True)
    (repo / "app/routes/__init__.py").write_text("")
    (repo / "app/routes/document_routes.py").write_text(
        '"""HTTP route handlers for document retrieval."""\n\n'
        "from app.auth.membership import MembershipChecker\n"
        "from app.middleware.auth_middleware import AuthMiddleware\n"
        "from app.services.document_service import DocumentService\n\n\n"
        "def handle_get_documents(user_id: str, project_id: str) -> list[str]:\n"
        '    """Route handler: GET /projects/<project_id>/documents."""\n'
        "    membership = MembershipChecker()\n"
        "    middleware = AuthMiddleware(membership)\n"
        "    service = DocumentService()\n"
        "    middleware.enforce(user_id, project_id)\n"
        "    return service.get_documents(user_id, project_id)\n"
    )


def _apply_scenario_c_harmless_rename(repo: Path) -> None:
    """is_member is renamed to is_project_member, consistently, at both
    the definition and the call site. Enforcement is unchanged."""
    (repo / "app/auth/membership.py").write_text(
        '"""Project membership checks."""\n\n'
        '_PROJECT_MEMBERS = {"proj-1": {"user-1", "user-2"}}\n\n\n'
        "class MembershipChecker:\n"
        '    """Checks whether a user belongs to a project."""\n\n'
        "    def is_project_member(self, user_id: str, project_id: str) -> bool:\n"
        "        return user_id in _PROJECT_MEMBERS.get(project_id, set())\n"
    )
    (repo / "app/services/document_service.py").write_text(
        '"""Serves project documents to authorized members."""\n\n'
        "from app.auth.membership import MembershipChecker\n\n\n"
        "class DocumentService:\n"
        '    """Retrieves documents for a project, enforcing membership."""\n\n'
        "    def __init__(self, membership: MembershipChecker) -> None:\n"
        "        self.membership = membership\n\n"
        "    def get_documents(self, user_id: str, project_id: str) -> list[str]:\n"
        '        """Return a project\'s documents if the user is a member."""\n'
        "        if not self.membership.is_project_member(user_id, project_id):\n"
        '            raise PermissionError("not a project member")\n'
        "        return self._fetch(project_id)\n\n"
        "    def _fetch(self, project_id: str) -> list[str]:\n"
        '        return [f"{project_id}/doc1.txt", f"{project_id}/doc2.txt"]\n'
    )


def _apply_scenario_d_ambiguous_bypass(repo: Path) -> None:
    """A new, undocumented bypass condition is added alongside the
    membership check -- genuinely unclear whether this is a sanctioned
    feature or a security hole."""
    (repo / "app/services/document_service.py").write_text(
        '"""Serves project documents to authorized members."""\n\n'
        "from app.auth.membership import MembershipChecker\n\n\n"
        "def _is_support_staff(user_id: str) -> bool:\n"
        '    return user_id.startswith("support-")\n\n\n'
        "class DocumentService:\n"
        '    """Retrieves documents for a project, enforcing membership."""\n\n'
        "    def __init__(self, membership: MembershipChecker) -> None:\n"
        "        self.membership = membership\n\n"
        "    def get_documents(self, user_id: str, project_id: str) -> list[str]:\n"
        '        """Return a project\'s documents if the user is a member."""\n'
        "        if not self.membership.is_member(user_id, project_id) and not _is_support_staff(user_id):\n"
        '            raise PermissionError("not a project member")\n'
        "        return self._fetch(project_id)\n\n"
        "    def _fetch(self, project_id: str) -> list[str]:\n"
        '        return [f"{project_id}/doc1.txt", f"{project_id}/doc2.txt"]\n'
    )


# --- scenario 1: removed check, nothing replaces it -> finding --------------


def test_scenario_removed_check_produces_a_finding(tmp_path: Path) -> None:
    repo, base_sha, conn = _setup(tmp_path, _apply_scenario_a_removed_check)
    context = build_tool_context(repo, base_sha, "HEAD", conn)
    result = inspect_symbol(context, GET_DOCUMENTS, revision="head")
    assert result is not None
    source = context.read_source("head", result.file)
    quoted_line = source.splitlines()[result.source.line_start - 1].strip()
    req_id = _requirement_id(conn)

    script = [
        _tool_call("inspect_symbol", {"qualified_name": GET_DOCUMENTS, "revision": "head"}, "c1"),
        _tool_call("inspect_callers", {"qualified_name": "app.auth.membership.MembershipChecker.is_member", "revision": "head"}, "c2"),
        _tool_call("search_code", {"query": "membership authorization enforce", "revision": "head"}, "c3"),
        _submit_finding_call(
            "c4",
            verdict="spec_violation_likely",
            requirement_ids=[req_id],
            changed_symbol_ids=[GET_DOCUMENTS],
            summary="The membership check in DocumentService.get_documents was removed and no equivalent enforcement exists elsewhere.",
            reasoning="Inspected get_documents (no check), searched for callers of is_member (none) and any authorization code elsewhere (none found).",
            citations=[
                {
                    "evidence_id": "ev-1",
                    "file": result.file,
                    "line_start": result.source.line_start,
                    "line_end": result.source.line_start,
                    "quote": quoted_line,
                }
            ],
            model_confidence=0.9,
        ),
    ]
    fake = ScriptedInvestigatorFake(scripts={GET_DOCUMENTS: script}, default_script=_default_abstain_script())

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)
    published = [r for r in results if r.decision == "publish"]

    assert len(published) == 1
    assert published[0].finding.verdict == FindingVerdict.SPEC_VIOLATION_LIKELY


# --- scenario 2: moved to middleware -> no finding ---------------------------


def test_scenario_moved_to_middleware_produces_no_finding(tmp_path: Path) -> None:
    repo, base_sha, conn = _setup(tmp_path, _apply_scenario_b_moved_to_middleware)
    context = build_tool_context(repo, base_sha, "HEAD", conn)
    result = inspect_symbol(context, GET_DOCUMENTS, revision="head")
    assert result is not None

    script = [
        _tool_call("inspect_symbol", {"qualified_name": GET_DOCUMENTS, "revision": "head"}, "c1"),
        _tool_call("search_code", {"query": "membership authorization enforce", "revision": "head"}, "c2"),
        _tool_call("inspect_callers", {"qualified_name": GET_DOCUMENTS, "revision": "head"}, "c3"),
        _tool_call(
            "inspect_symbol",
            {"qualified_name": "app.routes.document_routes.handle_get_documents", "revision": "head"},
            "c4",
        ),
        _submit_finding_call(
            "c5",
            verdict="no_issue",
            changed_symbol_ids=[GET_DOCUMENTS],
            summary="The membership check moved from the service to route-level middleware; enforcement is preserved.",
            reasoning="get_documents no longer checks membership, but search_code found AuthMiddleware.enforce, and "
            "handle_get_documents calls middleware.enforce(...) immediately before calling service.get_documents(...) "
            "on every path -- enforcement still happens, just at a different layer.",
            model_confidence=0.85,
        ),
    ]
    fake = ScriptedInvestigatorFake(scripts={GET_DOCUMENTS: script}, default_script=_default_abstain_script())

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)
    published = [r for r in results if r.decision == "publish"]

    assert published == []


# --- scenario 3: harmless rename -> no finding -------------------------------


def test_scenario_harmless_rename_produces_no_finding(tmp_path: Path) -> None:
    repo, base_sha, conn = _setup(tmp_path, _apply_scenario_c_harmless_rename)

    script = [
        _tool_call(
            "inspect_diff",
            {"file": "app/services/document_service.py", "symbol": GET_DOCUMENTS},
            "c1",
        ),
        _tool_call(
            "search_code", {"query": "is_project_member membership", "revision": "head"}, "c2"
        ),
        _tool_call(
            "inspect_git_history",
            {"file": "app/auth/membership.py", "limit": 3},
            "c3",
        ),
        _submit_finding_call(
            "c4",
            verdict="no_issue",
            changed_symbol_ids=[GET_DOCUMENTS],
            summary="MembershipChecker.is_member was renamed to is_project_member; the check itself is unchanged.",
            reasoning="The diff shows the call site updated from is_member to is_project_member, and search_code "
            "confirms is_project_member exists with the same membership-checking logic -- a rename, not a removal.",
            model_confidence=0.85,
        ),
    ]
    fake = ScriptedInvestigatorFake(scripts={GET_DOCUMENTS: script}, default_script=_default_abstain_script())

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)
    published = [r for r in results if r.decision == "publish"]

    assert published == []


# --- scenario 4: ambiguous bypass -> insufficient evidence -------------------


def test_scenario_ambiguous_bypass_is_insufficient_evidence(tmp_path: Path) -> None:
    repo, base_sha, conn = _setup(tmp_path, _apply_scenario_d_ambiguous_bypass)

    script = [
        _tool_call("inspect_symbol", {"qualified_name": GET_DOCUMENTS, "revision": "head"}, "c1"),
        _tool_call(
            "inspect_symbol",
            {"qualified_name": "app.services.document_service._is_support_staff", "revision": "head"},
            "c2",
        ),
        _tool_call("search_requirements", {"query": "support staff access bypass"}, "c3"),
        _submit_finding_call(
            "c4",
            verdict="insufficient_evidence",
            changed_symbol_ids=[GET_DOCUMENTS],
            summary="A new, undocumented bypass condition was added; intent is unclear.",
            reasoning="get_documents now also allows access for _is_support_staff(user_id), a new function with no "
            "requirement or comment explaining it. search_requirements found nothing about support-staff access. "
            "Cannot determine whether this is a sanctioned feature or an unintended widening of access.",
            unresolved_questions=["Is support-staff access to project documents an intended feature?"],
            model_confidence=0.4,
        ),
    ]
    fake = ScriptedInvestigatorFake(scripts={GET_DOCUMENTS: script}, default_script=_default_abstain_script())

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)
    published = [r for r in results if r.decision == "publish"]

    assert published == []
    get_documents_result = next(
        r for r in results if GET_DOCUMENTS in r.finding.changed_symbol_ids
    )
    assert get_documents_result.finding.verdict == FindingVerdict.INSUFFICIENT_EVIDENCE
