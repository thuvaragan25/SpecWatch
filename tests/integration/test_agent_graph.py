"""Phase 8 acceptance: the Investigator's LangGraph loop -- termination,
budget/round enforcement, deduplication, invalid-call handling, and
evidence bookkeeping -- verified deterministically against a scripted
fake chat model (no live API key). The real provider (ChatAnthropic) is
a config change, never touched by these tests, per plan.md's rule that
standard tests stay deterministic and live-model calls are opt-in evals.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from specwatch.agent.investigator import run_investigation
from specwatch.agent.tools.context import ToolContext, build_tool_context
from specwatch.code.symbol_index import build_symbol_index
from specwatch.domain.enums import FindingVerdict
from specwatch.domain.models import RequirementCandidate
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

INVOICE_SEND = "app.services.invoice_service.InvoiceService.send"


class FakeToolCallingChatModel(GenericFakeChatModel):
    """GenericFakeChatModel replays scripted AIMessages (tool_calls
    included) regardless of what's bound -- BaseChatModel.bind_tools
    raises NotImplementedError by default, so this no-ops it."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolCallingChatModel":
        return self


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


def _candidates(tool_context: ToolContext) -> list[RequirementCandidate]:
    req_id = next(
        r.id for r in tool_context.requirement_repo.list() if r.title == "Invoice Approval"
    )
    return [
        RequirementCandidate(requirement_id=req_id, symbol_qualified_name=INVOICE_SEND, score=1.0, method="lexical")
    ]


def _submit_finding_call(call_id: str, **overrides: Any) -> AIMessage:
    args = {
        "verdict": "no_issue",
        "requirement_ids": [],
        "changed_symbol_ids": [],
        "summary": "No violation found.",
        "reasoning": "Investigated and found no issue.",
        "citations": [],
        "unresolved_questions": [],
        "model_confidence": 0.9,
        **overrides,
    }
    return AIMessage(content="", tool_calls=[{"name": "submit_finding", "args": args, "id": call_id}])


def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


# --- normal path -------------------------------------------------------------


def test_investigation_completes_with_submitted_finding(tool_context: ToolContext) -> None:
    fake = FakeToolCallingChatModel(
        messages=iter(
            [
                _tool_call("inspect_symbol", {"qualified_name": INVOICE_SEND, "revision": "head"}, "c1"),
                _submit_finding_call("c2", verdict="spec_violation_likely", model_confidence=0.85),
            ]
        )
    )

    finding, final_state = run_investigation(
        investigation_id="inv-1",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=4,
    )

    assert finding.verdict == FindingVerdict.SPEC_VIOLATION_LIKELY
    assert final_state["status"] == "ready_to_finalize"
    assert len(final_state["evidence_items"]) == 1
    assert final_state["evidence_items"][0].tool_name == "inspect_symbol"
    assert final_state["remaining_tool_budget"] == 7  # one real tool call consumed


def test_evidence_id_surfaced_to_model_is_citable(tool_context: ToolContext) -> None:
    """The evidence_id the graph assigns (ev-1) must be exactly what a
    well-behaved model can cite -- this is the wiring Phase 9's verifier
    depends on."""
    fake = FakeToolCallingChatModel(
        messages=iter(
            [
                _tool_call("inspect_symbol", {"qualified_name": INVOICE_SEND, "revision": "head"}, "c1"),
                _submit_finding_call(
                    "c2",
                    citations=[
                        {"evidence_id": "ev-1", "file": "app/services/invoice_service.py", "line_start": 1, "line_end": 1, "quote": "x"}
                    ],
                ),
            ]
        )
    )

    finding, final_state = run_investigation(
        investigation_id="inv-2",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=4,
    )

    assert finding.citations[0].evidence_id == "ev-1"
    assert {e.id for e in final_state["evidence_items"]} == {"ev-1"}


# --- budget / round enforcement ----------------------------------------------


def test_tool_budget_exhaustion_forces_termination(tool_context: ToolContext) -> None:
    # model keeps requesting distinct tool calls forever, never submits
    endless = (
        _tool_call("search_code", {"query": f"invoice{i}"}, f"c{i}") for i in range(1, 100)
    )
    fake = FakeToolCallingChatModel(messages=endless)

    finding, final_state = run_investigation(
        investigation_id="inv-3",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=3,
        max_rounds=20,
    )

    assert final_state["status"] == "budget_exhausted"
    assert finding.verdict == FindingVerdict.INSUFFICIENT_EVIDENCE
    assert final_state["remaining_tool_budget"] == 0
    assert len(final_state["evidence_items"]) == 3  # never more than the budget


def test_round_budget_exhaustion_forces_termination(tool_context: ToolContext) -> None:
    endless = (
        _tool_call("search_code", {"query": f"invoice{i}"}, f"c{i}") for i in range(1, 100)
    )
    fake = FakeToolCallingChatModel(messages=endless)

    finding, final_state = run_investigation(
        investigation_id="inv-4",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=100,
        max_rounds=2,
    )

    assert final_state["status"] == "budget_exhausted"
    assert finding.verdict == FindingVerdict.INSUFFICIENT_EVIDENCE
    assert final_state["round"] == 2


# --- deduplication -------------------------------------------------------------


def test_duplicate_tool_calls_are_not_double_counted(tool_context: ToolContext) -> None:
    same_args = {"qualified_name": INVOICE_SEND, "revision": "head"}
    fake = FakeToolCallingChatModel(
        messages=iter(
            [
                _tool_call("inspect_symbol", same_args, "c1"),
                _tool_call("inspect_symbol", same_args, "c2"),  # exact repeat
                _submit_finding_call("c3"),
            ]
        )
    )

    _finding, final_state = run_investigation(
        investigation_id="inv-5",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=6,
    )

    assert len(final_state["evidence_items"]) == 1
    assert final_state["remaining_tool_budget"] == 7  # the repeat cost nothing


# --- invalid tool calls --------------------------------------------------------


def test_repeated_invalid_tool_calls_end_in_insufficient_evidence(tool_context: ToolContext) -> None:
    fake = FakeToolCallingChatModel(
        messages=iter(
            [
                _tool_call("not_a_real_tool", {}, "c1"),
                _tool_call("also_not_real", {}, "c2"),
                _submit_finding_call("c3"),  # should never be reached
            ]
        )
    )

    finding, final_state = run_investigation(
        investigation_id="inv-6",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=6,
    )

    assert final_state["status"] == "insufficient_evidence"
    assert finding.verdict == FindingVerdict.INSUFFICIENT_EVIDENCE
    assert final_state["round"] == 2  # stopped after the second invalid call, never reached round 3


def test_single_invalid_call_does_not_force_termination(tool_context: ToolContext) -> None:
    fake = FakeToolCallingChatModel(
        messages=iter(
            [
                _tool_call("not_a_real_tool", {}, "c1"),
                _submit_finding_call("c2", verdict="no_issue"),
            ]
        )
    )

    finding, final_state = run_investigation(
        investigation_id="inv-7",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=6,
    )

    assert final_state["status"] == "ready_to_finalize"
    assert finding.verdict == FindingVerdict.NO_ISSUE


# --- no tool call at all -------------------------------------------------------


def test_model_producing_no_tool_call_ends_in_insufficient_evidence(tool_context: ToolContext) -> None:
    fake = FakeToolCallingChatModel(messages=iter([AIMessage(content="I don't know what to do.")]))

    finding, final_state = run_investigation(
        investigation_id="inv-8",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=6,
    )

    assert finding.verdict == FindingVerdict.INSUFFICIENT_EVIDENCE
    assert final_state["status"] == "insufficient_evidence"


# --- prefetch -----------------------------------------------------------------


def test_prefetch_seeds_citable_evidence_without_spending_tool_budget(tool_context: ToolContext) -> None:
    fake = FakeToolCallingChatModel(
        messages=iter([_submit_finding_call("c1", verdict="spec_violation_likely", model_confidence=0.85)])
    )

    finding, final_state = run_investigation(
        investigation_id="inv-prefetch",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=4,
        diff_targets=[("app/services/invoice_service.py", INVOICE_SEND)],
        prefetch=True,
    )

    tools_used = [e.tool_name for e in final_state["evidence_items"]]
    assert "inspect_diff" in tools_used
    assert "inspect_requirement" in tools_used
    assert [e.id for e in final_state["evidence_items"]] == [
        f"ev-{i}" for i in range(1, len(tools_used) + 1)
    ]
    assert final_state["remaining_tool_budget"] == 8  # prefetch is free
    assert final_state["remaining_rounds"] == 3  # a single model call


def test_repeating_a_prefetched_call_is_deduplicated(tool_context: ToolContext) -> None:
    requirement_id = _candidates(tool_context)[0].requirement_id
    fake = FakeToolCallingChatModel(
        messages=iter(
            [
                _tool_call("inspect_requirement", {"requirement_id": requirement_id}, "c1"),
                _submit_finding_call("c2"),
            ]
        )
    )

    _finding, final_state = run_investigation(
        investigation_id="inv-dedupe",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=4,
        prefetch=True,
    )

    assert final_state["remaining_tool_budget"] == 8  # the repeat was not charged
    assert [e.tool_name for e in final_state["evidence_items"]].count("inspect_requirement") == 1


def test_prefetch_is_off_by_default(tool_context: ToolContext) -> None:
    fake = FakeToolCallingChatModel(messages=iter([_submit_finding_call("c1")]))

    _finding, final_state = run_investigation(
        investigation_id="inv-off",
        changed_symbol_qualified_names=[INVOICE_SEND],
        candidate_requirements=_candidates(tool_context),
        chat_model=fake,
        context=tool_context,
        max_tool_calls=8,
        max_rounds=4,
    )

    assert final_state["evidence_items"] == []
