"""search_code, inspect_symbol, inspect_callers, inspect_callees, inspect_diff.

Call graph tools only report what Phase 2's static resolver actually
found (see code.call_graph's module docstring): unresolved callees are
still returned, marked ``resolved=False``, rather than silently omitted
-- an unresolved call is evidence something might be there.
"""

import difflib

from pydantic import BaseModel

from specwatch.agent.tools.context import (
    MAX_CALL_DEPTH,
    MAX_CALL_RESULTS,
    MAX_DIFF_LINES,
    MAX_SEARCH_LIMIT,
    MAX_SOURCE_LINES,
    Revision,
    ToolContext,
    bounded_lines,
    truncate_text,
)
from specwatch.domain.enums import SymbolKind
from specwatch.domain.models import CodeSymbol, SourceLocation
from specwatch.git.client import diff_with_context
from specwatch.mapping.candidate_generator import BM25Index, Document
from specwatch.tests_index.pytest_parser import is_test_file

_SEARCHABLE_KINDS = {SymbolKind.CLASS, SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CONSTANT}


class CodeHit(BaseModel):
    qualified_name: str
    kind: SymbolKind
    file: str
    source: SourceLocation
    signature: str | None = None
    docstring_snippet: str | None = None
    score: float


class SymbolDetail(BaseModel):
    qualified_name: str
    kind: SymbolKind
    file: str
    source: SourceLocation
    signature: str | None = None
    docstring: str | None = None
    decorators: list[str]
    source_snippet: str
    caller_count: int
    callee_count: int


class CallerHit(BaseModel):
    caller_qualified_name: str
    depth: int
    call_site: SourceLocation


class CalleeHit(BaseModel):
    callee_reference: str
    callee_qualified_name: str | None
    resolved: bool
    depth: int
    call_site: SourceLocation


class LineRef(BaseModel):
    """One source line with its real line number in the file at that
    revision -- exactly what a citation needs (line number + verbatim text)."""

    line: int
    text: str


class DiffResult(BaseModel):
    # Field order matters: results are truncated for the prompt, so the
    # compact citation targets come before the bulky full sources.
    file: str
    symbol_qualified_name: str | None = None
    diff: str
    # Precise citation targets for the symbol-scoped diff: real file line
    # numbers and verbatim source text (no +/- diff markers).
    added_or_changed_lines: list[LineRef] = []
    removed_lines: list[LineRef] = []
    before_source: str | None = None
    after_source: str | None = None


def search_code(
    context: ToolContext, query: str, revision: Revision = "head", limit: int = 10
) -> list[CodeHit]:
    """Lexical (BM25) search over implementation symbols (test files
    excluded -- use search_tests for those) at ``revision``."""
    limit = min(limit, MAX_SEARCH_LIMIT)
    index = context.symbol_index_for(revision)
    symbols = [
        s
        for s in index.symbols.values()
        if s.kind in _SEARCHABLE_KINDS and not is_test_file(s.file.rsplit("/", 1)[-1])
    ]
    documents = [Document(id=s.qualified_name, text=_symbol_document_text(s)) for s in symbols]
    by_name = {s.qualified_name: s for s in symbols}

    bm25 = BM25Index(documents)
    hits: list[CodeHit] = []
    for qualified_name, score in bm25.search(query, limit=limit):
        symbol = by_name[qualified_name]
        hits.append(
            CodeHit(
                qualified_name=symbol.qualified_name,
                kind=symbol.kind,
                file=symbol.file,
                source=symbol.source,
                signature=symbol.signature,
                docstring_snippet=truncate_text(symbol.docstring) if symbol.docstring else None,
                score=score,
            )
        )
    return hits


def inspect_symbol(
    context: ToolContext, qualified_name: str, revision: Revision = "head"
) -> SymbolDetail | None:
    """Full detail for one symbol at ``revision``, or None if it doesn't
    exist there. Reports only caller/callee *counts* -- use
    inspect_callers/inspect_callees for the actual lists, so this tool's
    result stays a fixed, small size regardless of how connected a
    symbol is."""
    index = context.symbol_index_for(revision)
    symbol = index.get(qualified_name)
    if symbol is None:
        return None

    source = context.read_source(revision, symbol.file)
    snippet = (
        bounded_lines(source, symbol.source.line_start, symbol.source.line_end)
        if source is not None
        else ""
    )

    return SymbolDetail(
        qualified_name=symbol.qualified_name,
        kind=symbol.kind,
        file=symbol.file,
        source=symbol.source,
        signature=symbol.signature,
        docstring=symbol.docstring,
        decorators=symbol.decorators,
        source_snippet=snippet,
        caller_count=len(index.callers_of(qualified_name)),
        callee_count=len(index.callees_of(qualified_name)),
    )


def inspect_callers(
    context: ToolContext, qualified_name: str, revision: Revision = "head", depth: int = 1
) -> list[CallerHit]:
    """Bounded, resolved-only callers, up to ``depth`` hops away."""
    depth = max(1, min(depth, MAX_CALL_DEPTH))
    index = context.symbol_index_for(revision)

    hits: list[CallerHit] = []
    seen: set[str] = set()
    frontier = {qualified_name}
    for current_depth in range(1, depth + 1):
        next_frontier: set[str] = set()
        for target in frontier:
            for edge in index.callers_of(target):
                if edge.caller_qualified_name in seen:
                    continue
                seen.add(edge.caller_qualified_name)
                hits.append(
                    CallerHit(
                        caller_qualified_name=edge.caller_qualified_name,
                        depth=current_depth,
                        call_site=edge.source,
                    )
                )
                next_frontier.add(edge.caller_qualified_name)
                if len(hits) >= MAX_CALL_RESULTS:
                    return hits
        frontier = next_frontier
    return hits


def inspect_callees(
    context: ToolContext, qualified_name: str, revision: Revision = "head", depth: int = 1
) -> list[CalleeHit]:
    """Bounded callees, resolved and unresolved, up to ``depth`` hops
    away. Only resolved callees are expanded to the next hop -- an
    unresolved reference has no further symbol to traverse into."""
    depth = max(1, min(depth, MAX_CALL_DEPTH))
    index = context.symbol_index_for(revision)

    hits: list[CalleeHit] = []
    seen: set[str] = set()
    frontier = {qualified_name}
    for current_depth in range(1, depth + 1):
        next_frontier: set[str] = set()
        for source_symbol in frontier:
            for edge in index.callees_of(source_symbol):
                dedupe_key = f"{edge.callee_reference}@{edge.source.line_start}"
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                hits.append(
                    CalleeHit(
                        callee_reference=edge.callee_reference,
                        callee_qualified_name=edge.callee_qualified_name,
                        resolved=edge.resolved,
                        depth=current_depth,
                        call_site=edge.source,
                    )
                )
                if edge.resolved and edge.callee_qualified_name:
                    next_frontier.add(edge.callee_qualified_name)
                if len(hits) >= MAX_CALL_RESULTS:
                    return hits
        frontier = next_frontier
    return hits


def inspect_diff(context: ToolContext, file: str, symbol: str | None = None) -> DiffResult | None:
    """Before/after evidence for a file, or -- when ``symbol`` is given --
    for just that symbol's own source range on each side."""
    if symbol is None:
        diff_text = diff_with_context(context.repo, context.base, context.head, file)
        if not diff_text.strip():
            return None
        return DiffResult(file=file, diff=_bound_diff(diff_text))

    base_symbol = context.base_symbol_index.get(symbol)
    head_symbol = context.head_symbol_index.get(symbol)
    if base_symbol is None and head_symbol is None:
        return None

    before_source = _symbol_source(context, "base", base_symbol)
    after_source = _symbol_source(context, "head", head_symbol)

    diff_lines = list(
        difflib.unified_diff(
            (before_source or "").splitlines(),
            (after_source or "").splitlines(),
            fromfile=f"{file}@base",
            tofile=f"{file}@head",
            lineterm="",
        )
    )
    removed, added = _changed_line_refs(before_source, base_symbol, after_source, head_symbol)
    return DiffResult(
        file=file,
        symbol_qualified_name=symbol,
        before_source=before_source,
        after_source=after_source,
        diff=_bound_diff("\n".join(diff_lines)),
        added_or_changed_lines=added,
        removed_lines=removed,
    )


MAX_CHANGED_LINE_REFS = 30


def _changed_line_refs(
    before_source: str | None,
    base_symbol: CodeSymbol | None,
    after_source: str | None,
    head_symbol: CodeSymbol | None,
) -> tuple[list[LineRef], list[LineRef]]:
    """Map each changed line back to its real file line number. The symbol
    sources are slices starting at the symbol's first line, so line ``i``
    of a slice is file line ``symbol.source.line_start + i``."""
    before = (before_source or "").splitlines()
    after = (after_source or "").splitlines()
    before_start = base_symbol.source.line_start if base_symbol is not None else 1
    after_start = head_symbol.source.line_start if head_symbol is not None else 1

    removed: list[LineRef] = []
    added: list[LineRef] = []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed.extend(LineRef(line=before_start + i, text=before[i]) for i in range(i1, i2) if before[i].strip())
        added.extend(LineRef(line=after_start + j, text=after[j]) for j in range(j1, j2) if after[j].strip())
    return removed[:MAX_CHANGED_LINE_REFS], added[:MAX_CHANGED_LINE_REFS]


def _symbol_source(context: ToolContext, revision: Revision, symbol: CodeSymbol | None) -> str | None:
    if symbol is None:
        return None
    source = context.read_source(revision, symbol.file)
    if source is None:
        return None
    return bounded_lines(source, symbol.source.line_start, symbol.source.line_end, MAX_SOURCE_LINES)


def _bound_diff(diff_text: str) -> str:
    lines = diff_text.splitlines()
    if len(lines) <= MAX_DIFF_LINES:
        return diff_text
    omitted = len(lines) - MAX_DIFF_LINES
    return "\n".join(lines[:MAX_DIFF_LINES] + [f"... ({omitted} more lines truncated)"])


def _symbol_document_text(symbol: CodeSymbol) -> str:
    parts = [symbol.qualified_name, symbol.file]
    if symbol.docstring:
        parts.append(symbol.docstring)
    return " ".join(parts)
