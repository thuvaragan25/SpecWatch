"""Foundational domain models used across SpecWatch subsystems."""

from pydantic import BaseModel, Field, model_validator

from specwatch.domain.enums import (
    CandidateMethod,
    FileChangeType,
    FindingVerdict,
    PassageType,
    RequirementStatus,
    SymbolChangeType,
    SymbolKind,
)


class SourceLocation(BaseModel):
    """A citable range of source lines in a specific file.

    Every requirement, symbol, test, and citation in SpecWatch is anchored
    to one of these so that findings can be verified against real source.
    """

    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_range(self) -> "SourceLocation":
        if self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class Requirement(BaseModel):
    """A single extracted requirement or architecture rule.

    ``id`` is a stable fingerprint derived from document identity, heading,
    and normalized statement text (see specs.registry) so unrelated edits
    elsewhere in the document never change it.
    """

    id: str
    title: str
    statement: str
    passage_type: PassageType
    status: RequirementStatus = RequirementStatus.ACTIVE
    source: SourceLocation


class CodeSymbol(BaseModel):
    """A module, class, function, or method discovered by AST parsing.

    ``body_hash`` is a hash of the symbol's normalized (``ast.unparse``)
    structure, not its raw source text, so purely cosmetic edits (comments,
    whitespace, quote style) don't change it.
    """

    qualified_name: str
    kind: SymbolKind
    name: str
    file: str
    source: SourceLocation
    signature: str | None = None
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    body_hash: str


class CallEdge(BaseModel):
    """A call site, resolved to a qualified symbol name where possible.

    Unresolved calls (``resolved=False``, ``callee_qualified_name=None``)
    are kept, not dropped -- an unresolved call is evidence that something
    *might* be there, which downstream consumers (the agent, the impact
    filter) must not silently treat as "no caller exists".
    """

    caller_qualified_name: str
    callee_reference: str
    callee_qualified_name: str | None = None
    resolved: bool = False
    source: SourceLocation


class TestSymbol(BaseModel):
    """A discovered pytest test function or ``Test*``-class test method.

    ``referenced_symbols`` comes only from the resolved static call graph
    (code.call_graph) -- direct, high-confidence evidence that this test
    exercises a given implementation symbol. Weaker lexical candidate
    matching is a Phase 4 (mapping) concern, not this index.
    """

    qualified_name: str
    name: str
    file: str
    source: SourceLocation
    docstring: str | None = None
    fixtures: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)
    referenced_symbols: list[str] = Field(default_factory=list)


class RequirementCandidate(BaseModel):
    """A deterministically-generated candidate link from a requirement to
    a code symbol that might implement it. Not a claim of truth -- just a
    ranked starting point for the impact filter and agent investigation."""

    requirement_id: str
    symbol_qualified_name: str
    score: float
    method: CandidateMethod


class RequirementTestCandidate(BaseModel):
    """A deterministically-generated candidate link from a requirement to
    a test that might exercise it."""

    requirement_id: str
    test_qualified_name: str
    score: float
    method: CandidateMethod


class ChangedFile(BaseModel):
    """One file's change between base and head, from `git diff --name-status`
    plus unified-diff hunk headers (line ranges only, not full patch text)."""

    path: str
    change_type: FileChangeType
    old_path: str | None = None
    added_lines: list[int] = Field(default_factory=list)
    removed_lines: list[int] = Field(default_factory=list)


class ChangedSymbol(BaseModel):
    """A symbol whose body_hash differs (or which was added/removed)
    between base and head. ``base_symbol``/``head_symbol`` are None when
    the symbol doesn't exist on that side."""

    qualified_name: str
    change_type: SymbolChangeType
    base_symbol: CodeSymbol | None = None
    head_symbol: CodeSymbol | None = None


class Citation(BaseModel):
    """One piece of evidence a finding rests on.

    ``evidence_id`` must reference an evidence item the Investigator
    actually retrieved during its investigation (checked by the Phase 9
    verifier) -- a citation whose evidence_id wasn't retrieved this run is
    treated as fabricated, not as a citation with a typo.
    """

    evidence_id: str
    file: str
    line_start: int
    line_end: int
    quote: str

    @model_validator(mode="after")
    def _check_range(self) -> "Citation":
        if self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class FindingCandidate(BaseModel):
    """The Investigator's structured output. Only a *candidate* -- it must
    still pass the Phase 9 deterministic verifier before it can be
    published. The model has agency over investigation, not over truth.
    """

    verdict: FindingVerdict
    requirement_ids: list[str] = Field(default_factory=list)
    changed_symbol_ids: list[str] = Field(default_factory=list)
    summary: str
    reasoning: str
    citations: list[Citation] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    model_confidence: float = Field(ge=0.0, le=1.0)
