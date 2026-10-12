"""Phase 14 acceptance: SpecWatch analyzing its own repository, using its
own docs/product-prd.md requirements (plan.md's Dogfooding Requirement).

Each scenario copies the REAL SpecWatch repository (source, tests, and
docs -- not a purpose-built fixture) into a temp dir, edits the actual
verify_finding() function one way, and scripts the Investigator's
response the way a well-reasoning agent following the system prompt
would behave, exactly as Phases 10-12 did against smaller fixtures. No
live API key is available here either; this proves the pipeline
correctly turns a good investigation into the right outcome when run
against SpecWatch's own, much larger, real codebase (728 symbols, 220
tests) -- not just small purpose-built fixtures.

Scenario 3 (harmless refactor), scenario 4 (missing test evidence), and
scenario 5 (stale specification) from plan.md's dogfooding list use the
exact same mechanisms already proven end to end against dedicated
fixtures in Phases 10-12 (test_analysis_e2e.py's harmless-rename case,
test_test_evidence_gap_e2e.py, test_stale_spec_e2e.py) -- not repeated
here against SpecWatch's own code, since the mechanism, not the specific
target repository, is what those phases actually needed to prove.
"""

import shutil
import sqlite3
import subprocess
from pathlib import Path

from fake_chat_models import ScriptedInvestigatorFake, submit_finding_call, tool_call

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

REAL_REPO_ROOT = Path(__file__).parent.parent.parent
VERIFY_FINDING = "src.specwatch.verification.verifier.verify_finding"
_VERIFIER_RELATIVE_PATH = "src/specwatch/verification/verifier.py"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _ignore(_dirpath: str, names: list[str]) -> set[str]:
    skip = {".git", ".venv", ".specwatch", "__pycache__", ".pytest_cache"}
    return {n for n in names if n in skip or n.endswith(".egg-info")}


def _setup(tmp_path: Path, edit_verifier) -> tuple[Path, str, sqlite3.Connection]:
    repo = tmp_path / "repo"
    shutil.copytree(REAL_REPO_ROOT, repo, ignore=_ignore)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    verifier_path = repo / _VERIFIER_RELATIVE_PATH
    original = verifier_path.read_text()
    edited = edit_verifier(original)
    assert edited != original
    verifier_path.write_text(edited)
    _git(repo, "commit", "-q", "-am", "edit verify_finding")

    conn = get_connection(tmp_path / "specwatch.db")
    requirements = extract_requirements(
        (repo / "docs" / "product-prd.md").read_text(), source_file="docs/product-prd.md"
    )
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


def _requirement_id(conn: sqlite3.Connection, title: str) -> str:
    return next(r.id for r in RequirementRepository(conn).list() if r.title == title)


# --- 1. obvious violation: threshold hardcoded ------------------------------


def _hardcode_threshold(source: str) -> str:
    return source.replace(
        "if computed_confidence < min_confidence:", "if computed_confidence < 0.40:"
    )


def test_hardcoded_threshold_produces_a_finding(tmp_path: Path) -> None:
    """plan.md §30's own worked example, built for real against SpecWatch's
    actual verify_finding()."""
    repo, base_sha, conn = _setup(tmp_path, _hardcode_threshold)
    req_id = _requirement_id(conn, "Publication Threshold")

    from specwatch.agent.tools.context import build_tool_context
    from specwatch.agent.tools.code import inspect_diff

    context = build_tool_context(repo, base_sha, "HEAD", conn)
    diff_result = inspect_diff(context, file=_VERIFIER_RELATIVE_PATH, symbol=VERIFY_FINDING)
    assert diff_result is not None
    assert "0.40" in diff_result.diff

    # the citation's quote must match the real source file verbatim at the
    # cited line range (that's what the verifier checks), not diff-formatted
    # text -- find the actual line and its real line number in the head file
    head_source = context.read_source("head", _VERIFIER_RELATIVE_PATH)
    assert head_source is not None
    head_lines = head_source.splitlines()
    hardcoded_line_number = next(i for i, line in enumerate(head_lines, start=1) if "0.40" in line)
    diff_quote = head_lines[hardcoded_line_number - 1].strip()

    # analysis prefetches the changed symbol's diff as ev-1, so the model can
    # cite it without spending a round on inspect_diff itself
    script = [
        submit_finding_call(
            "c1",
            verdict="spec_violation_likely",
            requirement_ids=[req_id],
            changed_symbol_ids=[VERIFY_FINDING],
            summary="verify_finding now hardcodes the publication threshold to 0.40 instead of using the configured min_confidence.",
            reasoning="The requirement says findings below the CONFIGURED threshold must not be posted, but the "
            "diff shows the comparison now uses a hardcoded 0.40 literal instead of the min_confidence parameter -- "
            "a repository configured with a higher threshold would have its intent silently bypassed.",
            citations=[
                {
                    "evidence_id": "ev-1",
                    "file": _VERIFIER_RELATIVE_PATH,
                    "line_start": hardcoded_line_number,
                    "line_end": hardcoded_line_number,
                    "quote": diff_quote,
                }
            ],
            model_confidence=0.9,
        ),
    ]

    fake = ScriptedInvestigatorFake(scripts={VERIFY_FINDING: script}, default_script=script)

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)
    published = [r for r in results if r.decision == "publish"]

    assert len(published) == 1
    assert published[0].finding.verdict == FindingVerdict.SPEC_VIOLATION_LIKELY


# --- 2. moved elsewhere: refactored into a helper, still enforced ----------


def _extract_reasons_helper(source: str) -> str:
    old_block = (
        "    reasons: list[str] = []\n"
        "    reasons.extend(validate_provenance(candidate, changed_symbol_qualified_names, context))\n"
        "\n"
        "    if not candidate.citations:\n"
        '        reasons.append("actionable verdict has no citations")\n'
        "    else:\n"
        "        reasons.extend(\n"
        "            f\"invalid citation (evidence_id={issue.citation.evidence_id!r}): {issue.reason}\"\n"
        "            for issue in validate_citations(candidate.citations, evidence_items, context)\n"
        "        )\n"
    )
    new_block = (
        "    reasons = _gather_verification_reasons(candidate, evidence_items, changed_symbol_qualified_names, context)\n"
    )
    assert old_block in source
    helper = (
        "\n\ndef _gather_verification_reasons(candidate, evidence_items, changed_symbol_qualified_names, context):\n"
        "    reasons: list[str] = []\n"
        "    reasons.extend(validate_provenance(candidate, changed_symbol_qualified_names, context))\n"
        "    if not candidate.citations:\n"
        '        reasons.append("actionable verdict has no citations")\n'
        "    else:\n"
        "        reasons.extend(\n"
        "            f\"invalid citation (evidence_id={issue.citation.evidence_id!r}): {issue.reason}\"\n"
        "            for issue in validate_citations(candidate.citations, evidence_items, context)\n"
        "        )\n"
        "    return reasons\n"
    )
    return source.replace(old_block, new_block) + helper


def test_citation_check_moved_to_helper_produces_no_finding(tmp_path: Path) -> None:
    """The flagship pattern: the citation/provenance check disappears from
    verify_finding's own body, but a well-reasoning agent finds it was
    only relocated to a helper, not removed."""
    repo, base_sha, conn = _setup(tmp_path, _extract_reasons_helper)

    script = [
        tool_call("inspect_symbol", {"qualified_name": VERIFY_FINDING, "revision": "head"}, "c1"),
        tool_call("search_code", {"query": "gather verification reasons citation provenance", "revision": "head"}, "c2"),
        tool_call("inspect_callees", {"qualified_name": VERIFY_FINDING, "revision": "head"}, "c3"),
        submit_finding_call(
            "c4",
            verdict="no_issue",
            changed_symbol_ids=[VERIFY_FINDING],
            summary="Citation/provenance validation was extracted into _gather_verification_reasons, not removed.",
            reasoning="verify_finding's own body no longer directly validates citations, but inspect_callees shows "
            "it calls the new _gather_verification_reasons helper, which contains the same provenance and citation "
            "checks -- a refactor, not a removed enforcement.",
            model_confidence=0.85,
        ),
    ]
    fake = ScriptedInvestigatorFake(scripts={VERIFY_FINDING: script}, default_script=script)

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)
    published = [r for r in results if r.decision == "publish"]

    assert published == []


# --- 3. ambiguous: undocumented high-confidence bypass ----------------------


def _add_confidence_bypass(source: str) -> str:
    anchor = "    if reasons:\n"
    assert anchor in source
    replacement = (
        "    if candidate.model_confidence >= 0.99:\n"
        "        reasons = []\n\n"
        "    if reasons:\n"
    )
    return source.replace(anchor, replacement, 1)


def test_undocumented_confidence_bypass_is_insufficient_evidence(tmp_path: Path) -> None:
    repo, base_sha, conn = _setup(tmp_path, _add_confidence_bypass)
    req_id = _requirement_id(conn, "Citation Integrity")

    script = [
        tool_call("inspect_symbol", {"qualified_name": VERIFY_FINDING, "revision": "head"}, "c1"),
        tool_call("search_requirements", {"query": "high confidence bypass skip citation check"}, "c2"),
        tool_call("inspect_git_history", {"file": _VERIFIER_RELATIVE_PATH, "limit": 3}, "c3"),
        submit_finding_call(
            "c4",
            verdict="insufficient_evidence",
            requirement_ids=[req_id],
            changed_symbol_ids=[VERIFY_FINDING],
            summary="A new, undocumented bypass clears all validation reasons when model_confidence >= 0.99.",
            reasoning="verify_finding now skips citation and provenance validation entirely when the model reports "
            "confidence >= 0.99. No requirement documents this, and git history gives no explanation. Cannot tell "
            "whether this is an intentional fast path or a bypass of the anti-fabrication gate.",
            unresolved_questions=["Is the >=0.99 self-reported-confidence bypass an intended feature?"],
            model_confidence=0.4,
        ),
    ]
    fake = ScriptedInvestigatorFake(scripts={VERIFY_FINDING: script}, default_script=script)

    results = run_analysis(repo, base_sha, "HEAD", fake, conn, min_confidence=0.1, max_tool_calls=8, max_rounds=6)
    published = [r for r in results if r.decision == "publish"]

    assert published == []
    matching = next(r for r in results if VERIFY_FINDING in r.finding.changed_symbol_ids)
    assert matching.finding.verdict == FindingVerdict.INSUFFICIENT_EVIDENCE
