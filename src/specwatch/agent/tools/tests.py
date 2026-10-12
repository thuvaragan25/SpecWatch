"""search_tests, inspect_test.

Tests are always inspected at head (see context.py's module docstring).
search_tests combines whichever signals are given -- symbol (call-graph,
highest confidence), requirement_id (Phase 4 candidates), query
(lexical) -- as a union, then applies the overall limit.
"""

from pydantic import BaseModel

from specwatch.agent.tools.context import MAX_SEARCH_LIMIT, ToolContext, bounded_lines, truncate_text
from specwatch.domain.models import SourceLocation, TestSymbol
from specwatch.mapping.requirement_mapper import build_test_bm25_index


class TestHit(BaseModel):
    qualified_name: str
    file: str
    source: SourceLocation
    docstring_snippet: str | None = None


class TestDetail(BaseModel):
    qualified_name: str
    file: str
    source: SourceLocation
    docstring: str | None = None
    fixtures: list[str]
    assertions: list[str]
    referenced_symbols: list[str]
    source_snippet: str


def search_tests(
    context: ToolContext,
    query: str | None = None,
    symbol: str | None = None,
    requirement_id: str | None = None,
    limit: int = 10,
) -> list[TestHit]:
    limit = min(limit, MAX_SEARCH_LIMIT)
    matches: dict[str, TestSymbol] = {}

    if symbol:
        for test in context.head_test_index.tests_referencing(symbol):
            matches[test.qualified_name] = test

    if requirement_id:
        for candidate in context.candidate_repo.test_candidates_for_requirement(requirement_id):
            test = context.head_test_index.get(candidate.test_qualified_name)
            if test is not None:
                matches[test.qualified_name] = test

    if query:
        bm25 = build_test_bm25_index(context.head_test_index)
        for qualified_name, _score in bm25.search(query, limit=limit):
            test = context.head_test_index.get(qualified_name)
            if test is not None:
                matches[test.qualified_name] = test

    hits = [
        TestHit(
            qualified_name=test.qualified_name,
            file=test.file,
            source=test.source,
            docstring_snippet=truncate_text(test.docstring) if test.docstring else None,
        )
        for test in matches.values()
    ]
    return hits[:limit]


def inspect_test(context: ToolContext, qualified_name: str) -> TestDetail | None:
    test = context.head_test_index.get(qualified_name)
    if test is None:
        return None

    source = context.read_source("head", test.file)
    snippet = (
        bounded_lines(source, test.source.line_start, test.source.line_end)
        if source is not None
        else ""
    )

    return TestDetail(
        qualified_name=test.qualified_name,
        file=test.file,
        source=test.source,
        docstring=test.docstring,
        fixtures=test.fixtures,
        assertions=test.assertions,
        referenced_symbols=test.referenced_symbols,
        source_snippet=snippet,
    )
