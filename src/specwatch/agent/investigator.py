"""High-level entry point: seed one investigation and run it to completion.

The graph's own routing (agent.graph) is the real termination guarantee
(budget/round/invalid-call limits); the LangGraph recursion_limit passed
here is only a generous backstop against a runaway loop, not application
logic.
"""

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from specwatch.agent.graph import MAX_TOOL_RESULT_CHARS, _dump_result, _truncate, build_investigation_graph
from specwatch.agent.prompts import INVESTIGATOR_SYSTEM_PROMPT
from specwatch.agent.state import EvidenceItem, InvestigationState, ToolCallRecord, seed_investigation_state
from specwatch.agent.tools import code as code_tools
from specwatch.agent.tools import requirements as requirement_tools
from specwatch.agent.tools import tests as test_tools
from specwatch.agent.tools.context import ToolContext
from specwatch.domain.models import FindingCandidate, RequirementCandidate

# Only the strongest candidates are shown and prefetched; weak ones mostly
# make the model wander (and cost rounds).
MAX_CANDIDATE_REQUIREMENTS = 3
MAX_PREFETCHED_REQUIREMENTS = 2


def build_seed_message(
    changed_symbol_qualified_names: list[str],
    candidate_requirements: list[RequirementCandidate],
    test_gap_hints: dict[str, bool] | None = None,
    stale_spec_hints: dict[str, bool] | None = None,
    requirement_texts: dict[str, tuple[str, str]] | None = None,
    prefetched: list[EvidenceItem] | None = None,
) -> str:
    test_gap_hints = test_gap_hints or {}
    requirement_texts = requirement_texts or {}
    stale_spec_hints = stale_spec_hints or {}
    lines = ["Changed symbols in this pull request:"]
    lines.extend(f"- {name}" for name in changed_symbol_qualified_names)
    lines.append("")
    lines.append("Candidate requirements that may be relevant (not yet confirmed):")
    for c in candidate_requirements:
        line = f"- {c.requirement_id} (score={c.score:.2f}, method={c.method.value})"
        if test_gap_hints.get(c.requirement_id):
            line += (
                " -- NOTE: this requirement's statement discusses a prohibition/denial "
                "and has no candidate test evidence at all; consider whether "
                "test_evidence_gap is the right verdict, after checking whether an "
                "existing test actually covers the negative case."
            )
        if stale_spec_hints.get(c.requirement_id):
            line += (
                " -- NOTE: a changed constant's value doesn't share any number with this "
                "requirement's statement; confirm whether they describe the same parameter "
                "before concluding spec_may_be_stale -- a coincidental number is not proof."
            )
        lines.append(line)
        if c.requirement_id in requirement_texts:
            title, statement = requirement_texts[c.requirement_id]
            lines.append(f'  "{title}": {statement}')
    lines.append("")
    if prefetched:
        lines.append(
            "Evidence already gathered for you (cite these evidence_ids; calling the same "
            "tool again is a wasted round):"
        )
        for item in prefetched:
            lines.append(f"[{item.id}] {item.tool_name}({json.dumps(item.tool_args, sort_keys=True)})")
            lines.append(_truncate(item.content, MAX_TOOL_RESULT_CHARS))
        lines.append("")
        lines.append(
            "If this evidence is enough, call submit_finding now; otherwise make only the "
            "few targeted lookups you still need."
        )
        lines.append("")
    if requirement_texts:
        lines.append(
            "Requirement IDs are not searchable text. Call inspect_requirement on an ID "
            "to cite it; use the diff and code tools to judge the change."
        )
        lines.append("")
    lines.append(
        "Investigate whether this change violates, satisfies, or is ambiguous with "
        "respect to these requirements."
    )
    return "\n".join(lines)


def run_investigation(
    investigation_id: str,
    changed_symbol_qualified_names: list[str],
    candidate_requirements: list[RequirementCandidate],
    chat_model: BaseChatModel,
    context: ToolContext,
    max_tool_calls: int,
    max_rounds: int,
    test_gap_hints: dict[str, bool] | None = None,
    stale_spec_hints: dict[str, bool] | None = None,
    diff_targets: list[tuple[str, str]] | None = None,
    prefetch: bool = False,
) -> tuple[FindingCandidate, InvestigationState]:
    compiled_graph, _tools = build_investigation_graph(chat_model, context)

    candidate_requirements = sorted(candidate_requirements, key=lambda c: c.score, reverse=True)
    candidate_requirements = candidate_requirements[:MAX_CANDIDATE_REQUIREMENTS]
    evidence, history, signatures = (
        _prefetch_evidence(context, candidate_requirements, diff_targets or []) if prefetch else ([], [], [])
    )

    messages = [
        SystemMessage(content=INVESTIGATOR_SYSTEM_PROMPT),
        HumanMessage(
            content=build_seed_message(
                changed_symbol_qualified_names,
                candidate_requirements,
                test_gap_hints,
                stale_spec_hints,
                None if evidence else _requirement_texts(candidate_requirements, context),
                evidence,
            )
        ),
    ]
    initial_state = seed_investigation_state(
        investigation_id=investigation_id,
        changed_symbol_qualified_names=changed_symbol_qualified_names,
        candidate_requirement_ids=[c.requirement_id for c in candidate_requirements],
        messages=messages,
        max_tool_calls=max_tool_calls,
        max_rounds=max_rounds,
        evidence_items=evidence,
        tool_history=history,
        seen_tool_call_signatures=signatures,
    )

    final_state = compiled_graph.invoke(
        initial_state, config={"recursion_limit": max_rounds * 4 + 10}
    )
    final_candidate = final_state["final_candidate"]
    if final_candidate is None:
        raise RuntimeError("Investigation graph terminated without a final_candidate; this is a bug.")
    return final_candidate, final_state


def _requirement_texts(
    candidate_requirements: list[RequirementCandidate], context: ToolContext
) -> dict[str, tuple[str, str]]:
    texts: dict[str, tuple[str, str]] = {}
    for candidate in candidate_requirements:
        requirement = context.requirement_repo.get(candidate.requirement_id)
        if requirement is not None:
            texts[candidate.requirement_id] = (requirement.title, requirement.statement)
    return texts


def _prefetch_evidence(
    context: ToolContext,
    candidate_requirements: list[RequirementCandidate],
    diff_targets: list[tuple[str, str]],
) -> tuple[list[EvidenceItem], list[ToolCallRecord], list[str]]:
    """Run the lookups virtually every investigation starts with -- the
    changed symbols' diffs, the top requirements' full text, and the top
    requirement's candidate tests -- deterministically, before the first
    model call. They become ordinary evidence items (citable, and counted
    as already-seen so repeating them is deduplicated), saving the model
    several rounds. They do not consume the model's tool-call budget."""
    calls: list[tuple[str, dict, object]] = []
    for file, symbol in diff_targets:
        args = {"file": file, "symbol": symbol}
        calls.append(("inspect_diff", args, lambda a=args: code_tools.inspect_diff(context, **a)))
    seen_requirements: list[str] = []
    for candidate in candidate_requirements:
        if candidate.requirement_id not in seen_requirements:
            seen_requirements.append(candidate.requirement_id)
    for requirement_id in seen_requirements[:MAX_PREFETCHED_REQUIREMENTS]:
        args = {"requirement_id": requirement_id}
        calls.append(
            ("inspect_requirement", args, lambda a=args: requirement_tools.inspect_requirement(context, **a))
        )
    if seen_requirements:
        args = {"requirement_id": seen_requirements[0]}
        calls.append(("search_tests", args, lambda a=args: test_tools.search_tests(context, **a)))

    evidence: list[EvidenceItem] = []
    history: list[ToolCallRecord] = []
    signatures: list[str] = []
    for name, args, run in calls:
        result = run()
        if result is None:
            continue
        evidence_id = f"ev-{len(evidence) + 1}"
        evidence.append(
            EvidenceItem(id=evidence_id, tool_name=name, tool_args=args, round=0, content=_dump_result(result))
        )
        history.append(ToolCallRecord(round=0, tool_name=name, tool_args=args, evidence_id=evidence_id))
        signatures.append(f"{name}:{json.dumps(args, sort_keys=True, default=str)}")
    return evidence, history, signatures
