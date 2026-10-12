"""Phase 11 acceptance: a requirement that discusses prohibition/denial
but has no negative-case test evidence can be flagged test_evidence_gap,
run through the REAL pipeline (run_analysis), using the same auth
scenario fixture -- which genuinely only has a happy-path test, no test
for the denial case.

Note on the deterministic hint: has_test_evidence_gap() only fires
when a requirement has ZERO candidate tests at all -- deliberately
conservative (see mapping/test_gap.py). This fixture's requirement DOES
have one candidate test (the happy-path one, found via the call graph),
so the hint does NOT fire here -- matching plan.md §3.3's own worked
example exactly ("Tests found: happy-path member access only"). That
"thin but nonzero" judgment -- does an existing test actually cover the
negative case? -- is deliberately left to the agent, not automated.
"""

import shutil
import sqlite3
import subprocess
from pathlib import Path

from fake_chat_models import ScriptedInvestigatorFake, default_abstain_script, submit_finding_call, tool_call

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
HAPPY_PATH_TEST = "tests.test_document_service.test_member_can_retrieve_documents"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _setup(tmp_path: Path) -> tuple[Path, str, sqlite3.Connection, str]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_ROOT, repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    # a harmless, unrelated tweak to get_documents -- enforcement logic is
    # untouched, but it's a real body_hash change so the symbol still gets
    # investigated (and its requirement still has no negative-case test)
    (repo / "app/services/document_service.py").write_text(
        '"""Serves project documents to authorized members."""\n\n'
        "from app.auth.membership import MembershipChecker\n\n\n"
        "class DocumentService:\n"
        '    """Retrieves documents for a project, enforcing membership."""\n\n'
        "    def __init__(self, membership: MembershipChecker) -> None:\n"
        "        self.membership = membership\n\n"
        "    def get_documents(self, user_id: str, project_id: str) -> list[str]:\n"
        '        """Return a project\'s documents if the user is a member."""\n'
        "        if not self.membership.is_member(user_id, project_id):\n"
        '            raise PermissionError("not a project member")\n'
        "        return sorted(self._fetch(project_id))\n\n"
        "    def _fetch(self, project_id: str) -> list[str]:\n"
        '        return [f"{project_id}/doc1.txt", f"{project_id}/doc2.txt"]\n'
    )
    _git(repo, "commit", "-q", "-am", "sort returned documents")

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

    req_id = next(r.id for r in requirements if r.title == "Project Document Access")
    return repo, base_sha, conn, req_id


def test_deterministic_hint_does_not_fire_when_a_happy_path_test_exists(tmp_path: Path) -> None:
    """Confirms the conservative scope documented above: this fixture has
    a candidate test, so the automatic hint stays silent -- the agent has
    to notice the gap itself, which the next two tests exercise."""
    from specwatch.agent.tools.context import build_tool_context
    from specwatch.mapping.test_gap import has_test_evidence_gap

    repo, base_sha, conn, req_id = _setup(tmp_path)
    context = build_tool_context(repo, base_sha, "HEAD", conn)
    candidate_repo = CandidateRepository(conn)

    requirement = context.requirement_repo.get(req_id)
    test_candidates = candidate_repo.test_candidates_for_requirement(req_id)

    assert test_candidates  # the happy-path test IS a real candidate
    assert has_test_evidence_gap(requirement, test_candidates) is False


def _script(req_id: str, citations: list[dict]) -> list:
    return [
        tool_call("inspect_symbol", {"qualified_name": GET_DOCUMENTS, "revision": "head"}, "c1"),
        tool_call("search_tests", {"requirement_id": req_id}, "c2"),
        tool_call("inspect_test", {"qualified_name": HAPPY_PATH_TEST}, "c3"),
        submit_finding_call(
            "c4",
            verdict="test_evidence_gap",
            requirement_ids=[req_id],
            changed_symbol_ids=[GET_DOCUMENTS],
            summary="No negative-access test evidence found for project document access.",
            reasoning="The only related test exercises a member successfully retrieving documents; no test "
            "exercises a non-member being denied, even though the requirement explicitly requires denial.",
            citations=citations,
            model_confidence=0.75,
        ),
    ]


def test_scenario_no_negative_test_without_citation_is_suppressed(tmp_path: Path) -> None:
    repo, base_sha, conn, req_id = _setup(tmp_path)
    fake = ScriptedInvestigatorFake(
        scripts={GET_DOCUMENTS: _script(req_id, citations=[])},
        default_script=default_abstain_script(),
    )

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)

    matching = [r for r in results if GET_DOCUMENTS in r.finding.changed_symbol_ids]
    assert matching
    result = matching[0]
    assert result.finding.verdict == FindingVerdict.TEST_EVIDENCE_GAP
    # actionable verdict with zero citations -> suppressed, proving
    # Phase 9's "no citations, no publish" rule applies to this verdict
    # too, not just spec_violation_likely
    assert result.decision == "suppress"
    assert any("no citations" in reason for reason in result.reasons)


def test_scenario_no_negative_test_with_real_citation_publishes(tmp_path: Path) -> None:
    from specwatch.agent.tools.context import build_tool_context
    from specwatch.agent.tools.tests import inspect_test

    repo, base_sha, conn, req_id = _setup(tmp_path)
    context = build_tool_context(repo, base_sha, "HEAD", conn)
    test_detail = inspect_test(context, HAPPY_PATH_TEST)
    assert test_detail is not None
    source = context.read_source("head", test_detail.file)
    assert source is not None
    quoted_line = source.splitlines()[test_detail.source.line_start - 1].strip()

    citations = [
        {
            "evidence_id": "ev-3",
            "file": test_detail.file,
            "line_start": test_detail.source.line_start,
            "line_end": test_detail.source.line_start,
            "quote": quoted_line,
        }
    ]
    fake = ScriptedInvestigatorFake(
        scripts={GET_DOCUMENTS: _script(req_id, citations=citations)},
        default_script=default_abstain_script(),
    )

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)

    matching = [r for r in results if GET_DOCUMENTS in r.finding.changed_symbol_ids]
    assert matching
    result = matching[0]
    assert result.finding.verdict == FindingVerdict.TEST_EVIDENCE_GAP
    assert result.decision == "publish"
    assert result.reasons == []
