"""LLM-callable tool wrappers around the plain Phase 7 tool functions.

Each StructuredTool here is a thin adapter: an explicit args schema (for
reliable LLM tool-calling, not docstring inference) plus a closure that
calls straight through to the underlying plain-Python implementation in
agent.tools.{requirements,code,tests,git}. No logic lives here beyond
argument binding -- every tool remains independently testable without
these wrappers (see the Phase 7 tests).
"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from specwatch.agent.tools import code as code_tools
from specwatch.agent.tools import git as git_tools
from specwatch.agent.tools import requirements as requirement_tools
from specwatch.agent.tools import tests as test_tools
from specwatch.agent.tools.context import MAX_CALL_DEPTH, ToolContext
from specwatch.domain.models import FindingCandidate

SUBMIT_FINDING_TOOL_NAME = "submit_finding"


class SearchRequirementsArgs(BaseModel):
    query: str = Field(description="Natural-language search query over requirement text.")
    limit: int = Field(default=10, description="Max results, capped at 10.")


class InspectRequirementArgs(BaseModel):
    requirement_id: str = Field(description="A requirement ID, e.g. REQ-A1B2C3.")


class SearchCodeArgs(BaseModel):
    query: str = Field(description="Natural-language or identifier-like search query.")
    revision: str = Field(default="head", description='"base" or "head".')
    limit: int = Field(default=10, description="Max results, capped at 10.")


class InspectSymbolArgs(BaseModel):
    qualified_name: str = Field(description="Fully-qualified symbol name, e.g. pkg.module.Class.method.")
    revision: str = Field(default="head", description='"base" or "head".')


class InspectCallersArgs(BaseModel):
    qualified_name: str
    revision: str = Field(default="head")
    depth: int = Field(default=1, description=f"1-{MAX_CALL_DEPTH}.")


class InspectCalleesArgs(BaseModel):
    qualified_name: str
    revision: str = Field(default="head")
    depth: int = Field(default=1, description=f"1-{MAX_CALL_DEPTH}.")


class InspectDiffArgs(BaseModel):
    file: str = Field(description="Repo-relative file path.")
    symbol: str | None = Field(
        default=None, description="Optional qualified symbol name to scope the diff to."
    )


class SearchTestsArgs(BaseModel):
    query: str | None = Field(default=None, description="Lexical query over test names/docstrings.")
    symbol: str | None = Field(default=None, description="Find tests that call-graph-reference this symbol.")
    requirement_id: str | None = Field(default=None, description="Find tests candidate-linked to this requirement.")
    limit: int = Field(default=10, description="Max results, capped at 10.")


class InspectTestArgs(BaseModel):
    qualified_name: str


class InspectGitHistoryArgs(BaseModel):
    symbol: str | None = Field(default=None, description="Resolves to the file currently containing this symbol.")
    file: str | None = None
    limit: int = Field(default=5, description="Max commits, capped at 5.")


def build_agent_tools(context: ToolContext) -> list[StructuredTool]:
    """The investigation tool set, with ``context`` closed over so the
    LLM-facing schema never has to see or supply it."""
    return [
        StructuredTool.from_function(
            func=lambda **kw: requirement_tools.search_requirements(context, **kw),
            name="search_requirements",
            description=(
                "Search the requirement registry by natural-language query. Returns short "
                "hits (id, title, source, snippet) -- use inspect_requirement for full text."
            ),
            args_schema=SearchRequirementsArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: requirement_tools.inspect_requirement(context, **kw),
            name="inspect_requirement",
            description="Full detail (statement, source, status) for one requirement by ID.",
            args_schema=InspectRequirementArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: code_tools.search_code(context, **kw),
            name="search_code",
            description=(
                "Search implementation code symbols (classes/functions/methods/constants; "
                "test files excluded, use search_tests for those) by query."
            ),
            args_schema=SearchCodeArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: code_tools.inspect_symbol(context, **kw),
            name="inspect_symbol",
            description=(
                "Full detail (source, signature, docstring, decorators, caller/callee counts) "
                "for one symbol at base or head."
            ),
            args_schema=InspectSymbolArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: code_tools.inspect_callers(context, **kw),
            name="inspect_callers",
            description="Bounded, statically-resolved callers of a symbol, up to `depth` hops away.",
            args_schema=InspectCallersArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: code_tools.inspect_callees(context, **kw),
            name="inspect_callees",
            description=(
                "Bounded callees of a symbol, including unresolved references (resolved=false) "
                "-- an unresolved call means static analysis could not confirm the target, not "
                "that nothing is called there."
            ),
            args_schema=InspectCalleesArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: code_tools.inspect_diff(context, **kw),
            name="inspect_diff",
            description=(
                "Before/after diff for a file, or -- with `symbol` given -- for just that "
                "symbol's own source range on each side."
            ),
            args_schema=InspectDiffArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: test_tools.search_tests(context, **kw),
            name="search_tests",
            description="Find tests by symbol (call-graph evidence), requirement_id (candidate mapping), and/or lexical query.",
            args_schema=SearchTestsArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: test_tools.inspect_test(context, **kw),
            name="inspect_test",
            description="Full detail for one test: source, fixtures, assertions, referenced implementation symbols.",
            args_schema=InspectTestArgs,
        ),
        StructuredTool.from_function(
            func=lambda **kw: git_tools.inspect_git_history(context, **kw),
            name="inspect_git_history",
            description=(
                "Bounded commit history (sha, subject, single-file diffstat, never full "
                "patches) for a file or the file currently containing a symbol -- useful for "
                "spotting an intentional rename/refactor."
            ),
            args_schema=InspectGitHistoryArgs,
        ),
    ]


def build_submit_finding_tool() -> StructuredTool:
    """The "I'm done" tool: its schema IS FindingCandidate. Never actually
    invoked through `.func` -- the graph's execute_tools node intercepts
    calls to this tool by name and validates the args directly against
    FindingCandidate instead."""
    return StructuredTool.from_function(
        func=lambda **kw: kw,
        name=SUBMIT_FINDING_TOOL_NAME,
        description=(
            "Submit your final, structured investigation result. Call this exactly once, "
            "when you have enough evidence to reach a verdict or to explicitly abstain with "
            "insufficient_evidence. Every citation must reference an evidence_id you actually "
            "received from a tool call this investigation."
        ),
        args_schema=FindingCandidate,
    )
