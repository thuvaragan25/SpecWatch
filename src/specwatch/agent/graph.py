"""The Investigator's LangGraph loop.

Three nodes only, per plan.md: investigator (calls the model) ->
execute_tools (runs whatever it asked for, deterministically) ->
investigator, looping until the model calls submit_finding or a
deterministic budget/round/invalid-call limit forces finalize. All
budget enforcement, deduplication, and evidence bookkeeping happens in
plain Python in execute_tools/route_after_investigator -- the graph
orchestrates, it doesn't decide.
"""

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from specwatch.agent.state import EvidenceItem, InvestigationState, ToolCallRecord
from specwatch.agent.tools.registry import SUBMIT_FINDING_TOOL_NAME, build_agent_tools, build_submit_finding_tool
from specwatch.domain.enums import FindingVerdict
from specwatch.domain.models import FindingCandidate

MAX_INVALID_TOOL_CALL_STREAK = 2

# Prompt-size controls. The full tool output is always kept as evidence for
# the verifier; only what is *shown to the model* is trimmed, so small-context
# or rate-limited models can run a multi-round investigation.
MAX_TOOL_RESULT_CHARS = 2000
OLD_TOOL_RESULT_CHARS = 500
KEEP_RECENT_TOOL_RESULTS = 2


def build_investigation_graph(chat_model: BaseChatModel, context) -> tuple:
    """Returns (compiled_graph, tools) -- tools are exposed separately so
    callers (and tests) can inspect what was bound."""
    tools = [*build_agent_tools(context), build_submit_finding_tool()]
    bound_model = chat_model.bind_tools(tools)
    tool_registry = {tool.name: tool for tool in tools}

    graph = StateGraph(InvestigationState)
    graph.add_node("investigator", _make_investigator_node(bound_model))
    graph.add_node("execute_tools", _make_execute_tools_node(tool_registry))
    graph.add_node("finalize", _finalize_node)

    graph.add_edge(START, "investigator")
    graph.add_conditional_edges(
        "investigator",
        _route_after_investigator,
        {"execute_tools": "execute_tools", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "execute_tools",
        _route_after_execute_tools,
        {"investigator": "investigator", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)

    return graph.compile(), tools


def _make_investigator_node(bound_model: BaseChatModel):
    def investigator(state: InvestigationState) -> dict:
        response = bound_model.invoke(_compact_history(state["messages"]))
        return {
            "messages": [response],
            "round": state["round"] + 1,
            "remaining_rounds": state["remaining_rounds"] - 1,
        }

    return investigator


def _route_after_investigator(state: InvestigationState) -> str:
    """Only decides whether there's anything to execute -- submit_finding
    still has to go through execute_tools to be validated, so it must
    NOT be special-cased here (that was a real bug: routing it straight
    to finalize meant its args were never turned into final_candidate)."""
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []
    if not tool_calls:
        return "finalize"
    return "execute_tools"


def _route_after_execute_tools(state: InvestigationState) -> str:
    if state["status"] == "ready_to_finalize":
        return "finalize"
    if state["invalid_tool_call_streak"] >= MAX_INVALID_TOOL_CALL_STREAK:
        return "finalize"
    if state["remaining_tool_budget"] <= 0 or state["remaining_rounds"] <= 0:
        return "finalize"
    return "investigator"


def _make_execute_tools_node(tool_registry: dict[str, StructuredTool]):
    def execute_tools(state: InvestigationState) -> dict:
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []

        tool_messages: list[ToolMessage] = []
        evidence_items = list(state["evidence_items"])
        tool_history = list(state["tool_history"])
        seen = set(state["seen_tool_call_signatures"])
        remaining_budget = state["remaining_tool_budget"]
        invalid_streak = state["invalid_tool_call_streak"]
        final_candidate = state["final_candidate"]
        status = state["status"]

        for call in tool_calls:
            name = call["name"]
            args = call["args"]
            call_id = call["id"]

            if name == SUBMIT_FINDING_TOOL_NAME:
                try:
                    final_candidate = FindingCandidate.model_validate(args)
                    status = "ready_to_finalize"
                    tool_messages.append(
                        ToolMessage(content="Finding recorded.", tool_call_id=call_id)
                    )
                except ValidationError as exc:
                    tool_history.append(
                        ToolCallRecord(round=state["round"], tool_name=name, tool_args=args, error=str(exc))
                    )
                    tool_messages.append(
                        ToolMessage(content=f"Invalid submit_finding arguments: {exc}", tool_call_id=call_id)
                    )
                    invalid_streak += 1
                continue

            structured_tool = tool_registry.get(name)
            if structured_tool is None:
                tool_history.append(
                    ToolCallRecord(round=state["round"], tool_name=name, tool_args=args, error="unknown tool")
                )
                tool_messages.append(ToolMessage(content=f"Unknown tool: {name}", tool_call_id=call_id))
                invalid_streak += 1
                continue

            if remaining_budget <= 0:
                tool_messages.append(
                    ToolMessage(content="Tool budget exhausted for this investigation.", tool_call_id=call_id)
                )
                continue

            signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
            if signature in seen:
                tool_messages.append(
                    ToolMessage(
                        content="Already called with these exact arguments this investigation "
                        "-- see the earlier result.",
                        tool_call_id=call_id,
                    )
                )
                continue

            try:
                result = structured_tool.func(**args)
            except (ValidationError, TypeError) as exc:
                tool_history.append(
                    ToolCallRecord(round=state["round"], tool_name=name, tool_args=args, error=str(exc))
                )
                tool_messages.append(ToolMessage(content=f"Invalid arguments: {exc}", tool_call_id=call_id))
                invalid_streak += 1
                continue

            seen.add(signature)
            remaining_budget -= 1
            invalid_streak = 0

            evidence_id = f"ev-{len(evidence_items) + 1}"
            content = _dump_result(result)
            evidence_items.append(
                EvidenceItem(id=evidence_id, tool_name=name, tool_args=args, round=state["round"], content=content)
            )
            tool_history.append(
                ToolCallRecord(round=state["round"], tool_name=name, tool_args=args, evidence_id=evidence_id)
            )
            tool_messages.append(
                ToolMessage(
                    content=f"[{evidence_id}]\n{_truncate(content, MAX_TOOL_RESULT_CHARS)}",
                    tool_call_id=call_id,
                )
            )

        return {
            "messages": tool_messages,
            "evidence_items": evidence_items,
            "tool_history": tool_history,
            "seen_tool_call_signatures": list(seen),
            "remaining_tool_budget": remaining_budget,
            "invalid_tool_call_streak": invalid_streak,
            "final_candidate": final_candidate,
            "status": status,
        }

    return execute_tools


def _finalize_node(state: InvestigationState) -> dict:
    if state["final_candidate"] is not None:
        return {"status": "ready_to_finalize"}

    if state["invalid_tool_call_streak"] >= MAX_INVALID_TOOL_CALL_STREAK:
        status = "insufficient_evidence"
        reasoning = "Investigation ended after repeated invalid tool calls."
    elif state["remaining_tool_budget"] <= 0 or state["remaining_rounds"] <= 0:
        status = "budget_exhausted"
        reasoning = "Investigation ended: tool or round budget exhausted before a finding was submitted."
    else:
        status = "insufficient_evidence"
        reasoning = "Investigation ended without a submitted finding."

    fallback = FindingCandidate(
        verdict=FindingVerdict.INSUFFICIENT_EVIDENCE,
        requirement_ids=state["candidate_requirement_ids"],
        changed_symbol_ids=state["changed_symbol_qualified_names"],
        summary="No finding was submitted.",
        reasoning=reasoning,
        model_confidence=0.0,
    )
    return {"status": status, "final_candidate": fallback}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[truncated {len(text) - limit} chars; narrow the query for more]"


def _compact_history(messages: list) -> list:
    """The prompt view of the conversation: all but the most recent tool
    results are shortened, since their gist is already reflected in the
    model's own subsequent steps. Does not modify state."""
    tool_positions = [i for i, m in enumerate(messages) if isinstance(m, ToolMessage)]
    old = set(tool_positions[:-KEEP_RECENT_TOOL_RESULTS]) if KEEP_RECENT_TOOL_RESULTS else set(tool_positions)
    compacted = []
    for i, message in enumerate(messages):
        if i in old and isinstance(message.content, str) and len(message.content) > OLD_TOOL_RESULT_CHARS:
            message = message.model_copy(update={"content": _truncate(message.content, OLD_TOOL_RESULT_CHARS)})
        compacted.append(message)
    return compacted


def _dump_result(result: list[BaseModel] | BaseModel | None) -> str:
    if result is None:
        return json.dumps({"found": False})
    if isinstance(result, list):
        return json.dumps({"count": len(result), "results": [item.model_dump(mode="json") for item in result]})
    return result.model_dump_json()
