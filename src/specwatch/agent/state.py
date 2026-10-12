"""LangGraph investigation state and evidence bookkeeping.

EvidenceItem/ToolCallRecord are agent-internal bookkeeping, not core
domain entities -- Phase 9's verifier and reporting depend on
domain.models.FindingCandidate/Citation, never on this module, so they
stay usable and testable without any agent/LangGraph machinery running.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from specwatch.domain.models import FindingCandidate


class EvidenceItem(BaseModel):
    """One tool result the Investigator actually received this run. The
    verifier checks every citation's evidence_id against this list."""

    id: str
    tool_name: str
    tool_args: dict
    round: int
    content: str


class ToolCallRecord(BaseModel):
    """One tool-call attempt, successful or not -- kept for the
    investigation's audit trail (`specwatch investigate --show-tools`)."""

    round: int
    tool_name: str
    tool_args: dict
    evidence_id: str | None = None
    error: str | None = None


InvestigationStatus = Literal[
    "investigating", "ready_to_finalize", "insufficient_evidence", "budget_exhausted"
]


class InvestigationState(TypedDict):
    investigation_id: str
    changed_symbol_qualified_names: list[str]
    candidate_requirement_ids: list[str]

    messages: Annotated[list[BaseMessage], add_messages]

    round: int
    remaining_tool_budget: int
    remaining_rounds: int
    invalid_tool_call_streak: int

    evidence_items: list[EvidenceItem]
    tool_history: list[ToolCallRecord]
    seen_tool_call_signatures: list[str]

    status: InvestigationStatus
    final_candidate: FindingCandidate | None


def seed_investigation_state(
    investigation_id: str,
    changed_symbol_qualified_names: list[str],
    candidate_requirement_ids: list[str],
    messages: list[BaseMessage],
    max_tool_calls: int,
    max_rounds: int,
    evidence_items: list[EvidenceItem] | None = None,
    tool_history: list[ToolCallRecord] | None = None,
    seen_tool_call_signatures: list[str] | None = None,
) -> InvestigationState:
    return InvestigationState(
        investigation_id=investigation_id,
        changed_symbol_qualified_names=changed_symbol_qualified_names,
        candidate_requirement_ids=candidate_requirement_ids,
        messages=messages,
        round=0,
        remaining_tool_budget=max_tool_calls,
        remaining_rounds=max_rounds,
        invalid_tool_call_streak=0,
        evidence_items=evidence_items or [],
        tool_history=tool_history or [],
        seen_tool_call_signatures=seen_tool_call_signatures or [],
        status="investigating",
        final_candidate=None,
    )
