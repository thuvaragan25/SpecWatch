"""Shared context and result-bounding helpers for agent tools.

``head`` is assumed to be the checked-out working tree (true for both the
CLI's typical `--head HEAD` usage and the Phase 13 GitHub Action, which
checks out the PR head before analyzing) -- ``base`` is read via `git
show` with no checkout required, since it usually isn't the current
working tree. Test discovery (search_tests/inspect_test) is head-only, so
it consistently uses the same working-tree source as head_symbol_index.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from specwatch.code.symbol_index import SymbolIndex, build_symbol_index
from specwatch.git.client import show_file_at_revision
from specwatch.git.diff import build_symbol_index_at_revision
from specwatch.storage.repositories import CandidateRepository, RequirementRepository
from specwatch.tests_index.index import PytestIndex, build_test_index

Revision = Literal["base", "head"]

MAX_SOURCE_LINES = 150
MAX_DIFF_LINES = 200
MAX_SNIPPET_CHARS = 300
MAX_COMMIT_HISTORY_LIMIT = 5
MAX_CALL_RESULTS = 20
MAX_CALL_DEPTH = 2
MAX_SEARCH_LIMIT = 10


@dataclass
class ToolContext:
    repo: Path
    base: str
    head: str
    base_symbol_index: SymbolIndex
    head_symbol_index: SymbolIndex
    head_test_index: PytestIndex
    requirement_repo: RequirementRepository
    candidate_repo: CandidateRepository

    def symbol_index_for(self, revision: Revision) -> SymbolIndex:
        return self.base_symbol_index if revision == "base" else self.head_symbol_index

    def revision_ref(self, revision: Revision) -> str:
        return self.base if revision == "base" else self.head

    def read_source(self, revision: Revision, file: str) -> str | None:
        return show_file_at_revision(self.repo, self.revision_ref(revision), file)


def build_tool_context(repo: Path, base: str, head: str, conn: sqlite3.Connection) -> ToolContext:
    head_symbol_index = build_symbol_index(repo)
    base_symbol_index = build_symbol_index_at_revision(repo, base)
    head_test_index = build_test_index(repo, head_symbol_index)

    return ToolContext(
        repo=repo,
        base=base,
        head=head,
        base_symbol_index=base_symbol_index,
        head_symbol_index=head_symbol_index,
        head_test_index=head_test_index,
        requirement_repo=RequirementRepository(conn),
        candidate_repo=CandidateRepository(conn),
    )


def bounded_lines(source: str, line_start: int, line_end: int, max_lines: int = MAX_SOURCE_LINES) -> str:
    """Extract a 1-indexed inclusive line range, truncated with a marker
    if it exceeds ``max_lines``."""
    lines = source.splitlines()
    start = max(line_start - 1, 0)
    end = min(line_end, len(lines))
    snippet_lines = lines[start:end]
    if len(snippet_lines) > max_lines:
        omitted = len(snippet_lines) - max_lines
        snippet_lines = snippet_lines[:max_lines] + [f"... ({omitted} more lines truncated)"]
    return "\n".join(snippet_lines)


def truncate_text(text: str, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
