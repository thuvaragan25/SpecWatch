"""Phase 12 acceptance: a changed numeric constant whose value no longer
matches a candidate requirement's stated number can be flagged
spec_may_be_stale, run through the REAL pipeline -- plan.md §3.2's own
TOKEN_TTL_MINUTES example, built for real rather than left illustrative.
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

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "token_ttl_repo"
TOKEN_TTL = "app.auth.tokens.TOKEN_TTL_MINUTES"

_HEAD_TOKENS_MODULE = (
    '"""Password reset token generation and validation."""\n\n'
    "TOKEN_TTL_MINUTES = 60\n\n\n"
    "class PasswordResetTokenService:\n"
    '    """Issues and validates password reset tokens."""\n\n'
    "    def issue_token(self, user_id: str) -> str:\n"
    '        """Create a new password reset token for a user."""\n'
    '        return f"token-for-{user_id}"\n\n'
    "    def validate_token(self, token: str) -> bool:\n"
    '        """Check whether a password reset token is still valid."""\n'
    '        return token.startswith("token-for-")\n'
)


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

    (repo / "app/auth/tokens.py").write_text(_HEAD_TOKENS_MODULE)
    _git(repo, "commit", "-q", "-am", "increase token ttl to 60 minutes")

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

    req_id = next(r.id for r in requirements if r.title == "Password Reset Tokens")
    return repo, base_sha, conn, req_id


def test_deterministic_hint_fires_for_mismatched_constant(tmp_path: Path) -> None:
    from specwatch.agent.tools.context import build_tool_context
    from specwatch.mapping.stale_spec import has_constant_value_mismatch

    repo, base_sha, conn, req_id = _setup(tmp_path)
    context = build_tool_context(repo, base_sha, "HEAD", conn)
    constant = context.head_symbol_index.get(TOKEN_TTL)
    requirement = context.requirement_repo.get(req_id)

    assert constant is not None
    assert constant.signature == "60"
    assert has_constant_value_mismatch(constant, requirement) is True


def test_scenario_stale_constant_produces_spec_may_be_stale_finding(tmp_path: Path) -> None:
    repo, base_sha, conn, req_id = _setup(tmp_path)
    from specwatch.agent.tools.context import build_tool_context
    from specwatch.agent.tools.requirements import inspect_requirement

    context = build_tool_context(repo, base_sha, "HEAD", conn)
    requirement_detail = inspect_requirement(context, req_id)
    assert requirement_detail is not None
    prd_source = context.read_source("head", requirement_detail.source.file) or (repo / "docs/prd.md").read_text()
    quoted_req_line = prd_source.splitlines()[requirement_detail.source.line_start - 1].strip()

    script = [
        tool_call("inspect_symbol", {"qualified_name": TOKEN_TTL, "revision": "head"}, "c1"),
        tool_call("inspect_requirement", {"requirement_id": req_id}, "c2"),
        tool_call("inspect_diff", {"file": "app/auth/tokens.py", "symbol": TOKEN_TTL}, "c3"),
        submit_finding_call(
            "c4",
            verdict="spec_may_be_stale",
            requirement_ids=[req_id],
            changed_symbol_ids=[TOKEN_TTL],
            summary="TOKEN_TTL_MINUTES is now 60, but the requirement still says tokens expire after 30 minutes.",
            reasoning="The constant changed from 30 to 60 deliberately (the diff shows a clean, intentional edit, "
            "not a bug), but the requirement's wording was not updated to match the new value.",
            citations=[
                {
                    "evidence_id": "ev-2",
                    "file": requirement_detail.source.file,
                    "line_start": requirement_detail.source.line_start,
                    "line_end": requirement_detail.source.line_start,
                    "quote": quoted_req_line,
                }
            ],
            model_confidence=0.8,
        ),
    ]
    fake = ScriptedInvestigatorFake(scripts={TOKEN_TTL: script}, default_script=default_abstain_script())

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)
    published = [r for r in results if r.decision == "publish"]

    assert len(published) == 1
    assert published[0].finding.verdict == FindingVerdict.SPEC_MAY_BE_STALE
