"""Repository-wide Python symbol index.

Walks a directory tree, parses every ``.py`` file, and resolves the
approximate call graph across all of them.
"""

from pathlib import Path

from specwatch.code.call_graph import resolve_calls
from specwatch.code.python_parser import ParsedModule, module_qualified_name, parse_module
from specwatch.domain.models import CallEdge, CodeSymbol

SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".specwatch",
    ".pytest_cache",
}


def discover_python_files(root: Path) -> list[Path]:
    """Find every ``.py`` file under ``root``, skipping noise directories."""
    files = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


class SymbolIndex:
    """In-memory index of code symbols and resolved call edges."""

    def __init__(self) -> None:
        self.symbols: dict[str, CodeSymbol] = {}
        self.call_edges: list[CallEdge] = []

    def get(self, qualified_name: str) -> CodeSymbol | None:
        return self.symbols.get(qualified_name)

    def callers_of(self, qualified_name: str) -> list[CallEdge]:
        """Resolved call edges whose target is ``qualified_name``."""
        return [
            edge
            for edge in self.call_edges
            if edge.resolved and edge.callee_qualified_name == qualified_name
        ]

    def callees_of(self, qualified_name: str) -> list[CallEdge]:
        """All call edges (resolved and unresolved) made by ``qualified_name``."""
        return [edge for edge in self.call_edges if edge.caller_qualified_name == qualified_name]


def assemble_index(parsed_modules: list[ParsedModule]) -> SymbolIndex:
    """Build a :class:`SymbolIndex` from already-parsed modules, resolving
    the call graph across all of them. Shared by ``build_symbol_index``
    (working tree) and ``git.diff.build_symbol_index_at_revision``
    (``git show``, no checkout required)."""
    index = SymbolIndex()
    for module in parsed_modules:
        for symbol in module.symbols:
            index.symbols[symbol.qualified_name] = symbol
    index.call_edges = resolve_calls(parsed_modules, index)
    return index


def build_symbol_index(root: Path) -> SymbolIndex:
    """Parse every Python file under ``root`` and resolve its call graph."""
    root = root.resolve()
    parsed_modules: list[ParsedModule] = []

    for file_path in discover_python_files(root):
        try:
            source = file_path.read_text()
        except (UnicodeDecodeError, OSError):
            continue

        rel_path = file_path.relative_to(root)
        module_name = module_qualified_name(rel_path)
        rel_file = str(rel_path)
        try:
            parsed = parse_module(source, file=rel_file, module_name=module_name)
        except SyntaxError:
            continue
        parsed_modules.append(parsed)

    return assemble_index(parsed_modules)
