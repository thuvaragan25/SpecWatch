"""Base/head diff -> changed files -> changed symbols.

Symbol-level changes are determined by comparing qualified names and
``body_hash`` between the base and head symbol tables for each changed
Python file -- not by textual line diffing -- so purely cosmetic edits
(formatting, comments, quote style) never register as a symbol change.
"""

import re
from pathlib import Path

from specwatch.code.python_parser import ParsedModule, module_qualified_name, parse_module
from specwatch.code.symbol_index import SKIP_DIR_NAMES, SymbolIndex, assemble_index
from specwatch.domain.enums import FileChangeType, SymbolChangeType, SymbolKind
from specwatch.domain.models import ChangedFile, ChangedSymbol, CodeSymbol
from specwatch.git.client import (
    diff_name_status,
    diff_unified,
    list_files_at_revision,
    show_file_at_revision,
)

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

_FILE_STATUS_MAP = {
    "A": FileChangeType.ADDED,
    "M": FileChangeType.MODIFIED,
    "D": FileChangeType.DELETED,
    "R": FileChangeType.RENAMED,
}


def changed_files(repo: Path, base: str, head: str) -> list[ChangedFile]:
    """Every changed ``.py`` file between ``base`` and ``head``, with
    zero-context hunk line ranges (not full patch text)."""
    files: list[ChangedFile] = []
    for entry in diff_name_status(repo, base, head):
        if not entry["path"].endswith(".py"):
            continue
        change_type = _FILE_STATUS_MAP.get(entry["status"][0], FileChangeType.MODIFIED)
        added, removed = _parse_hunk_line_ranges(diff_unified(repo, base, head, entry["path"]))
        files.append(
            ChangedFile(
                path=entry["path"],
                old_path=entry["old_path"],
                change_type=change_type,
                added_lines=added,
                removed_lines=removed,
            )
        )
    return files


def changed_symbols(repo: Path, base: str, head: str, root: Path) -> list[ChangedSymbol]:
    """Compare base vs head symbol tables for every changed Python file.

    ``root`` should be the same repository root used for the full
    :func:`specwatch.code.symbol_index.build_symbol_index` run, so that
    qualified names here match qualified names everywhere else.
    """
    results: list[ChangedSymbol] = []
    for file in changed_files(repo, base, head):
        base_path = file.old_path or file.path
        head_path = file.path

        base_source = (
            None if file.change_type == FileChangeType.ADDED else show_file_at_revision(repo, base, base_path)
        )
        head_source = (
            None if file.change_type == FileChangeType.DELETED else show_file_at_revision(repo, head, head_path)
        )

        base_symbols = _symbols_by_qualified_name(base_source, base_path)
        head_symbols = _symbols_by_qualified_name(head_source, head_path)

        results.extend(_diff_symbol_tables(base_symbols, head_symbols))
    return results


def build_symbol_index_at_revision(repo: Path, revision: str) -> SymbolIndex:
    """Build a full-repository :class:`SymbolIndex` from ``git show``
    output at ``revision``, without needing it checked out on disk. Used
    by the agent tool layer to inspect the "base" side of a PR while the
    working tree holds "head"."""
    parsed_modules: list[ParsedModule] = []
    for rel_file in list_files_at_revision(repo, revision):
        rel_path = Path(rel_file)
        if rel_path.suffix != ".py" or any(part in SKIP_DIR_NAMES for part in rel_path.parts):
            continue
        source = show_file_at_revision(repo, revision, rel_file)
        if source is None:
            continue
        module_name = module_qualified_name(rel_path)
        try:
            parsed = parse_module(source, file=rel_file, module_name=module_name)
        except SyntaxError:
            continue
        parsed_modules.append(parsed)
    return assemble_index(parsed_modules)


def _symbols_by_qualified_name(source: str | None, rel_path: str) -> dict[str, CodeSymbol]:
    """Excludes the MODULE-kind symbol: its body_hash covers the whole
    file, so it would trivially "change" on every touched file with zero
    discriminative signal -- ChangedFile already captures that."""
    if source is None:
        return {}
    module_name = module_qualified_name(Path(rel_path))
    try:
        parsed = parse_module(source, file=rel_path, module_name=module_name)
    except SyntaxError:
        return {}
    return {
        symbol.qualified_name: symbol
        for symbol in parsed.symbols
        if symbol.kind != SymbolKind.MODULE
    }


def _diff_symbol_tables(
    base_symbols: dict[str, CodeSymbol], head_symbols: dict[str, CodeSymbol]
) -> list[ChangedSymbol]:
    changes: list[ChangedSymbol] = []
    for qualified_name in sorted(set(base_symbols) | set(head_symbols)):
        base_symbol = base_symbols.get(qualified_name)
        head_symbol = head_symbols.get(qualified_name)

        if base_symbol is None:
            changes.append(
                ChangedSymbol(
                    qualified_name=qualified_name,
                    change_type=SymbolChangeType.ADDED,
                    head_symbol=head_symbol,
                )
            )
        elif head_symbol is None:
            changes.append(
                ChangedSymbol(
                    qualified_name=qualified_name,
                    change_type=SymbolChangeType.REMOVED,
                    base_symbol=base_symbol,
                )
            )
        elif base_symbol.body_hash != head_symbol.body_hash:
            changes.append(
                ChangedSymbol(
                    qualified_name=qualified_name,
                    change_type=SymbolChangeType.MODIFIED,
                    base_symbol=base_symbol,
                    head_symbol=head_symbol,
                )
            )
    return changes


def _parse_hunk_line_ranges(diff_text: str) -> tuple[list[int], list[int]]:
    added: list[int] = []
    removed: list[int] = []
    for line in diff_text.splitlines():
        match = _HUNK_RE.match(line)
        if not match:
            continue
        old_start, old_count, new_start, new_count = match.groups()
        old_count = int(old_count) if old_count is not None else 1
        new_count = int(new_count) if new_count is not None else 1
        if old_count:
            removed.extend(range(int(old_start), int(old_start) + old_count))
        if new_count:
            added.extend(range(int(new_start), int(new_start) + new_count))
    return added, removed
