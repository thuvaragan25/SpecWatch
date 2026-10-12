"""Repository-wide pytest test index.

Mirrors ``code.symbol_index.build_symbol_index``, but layered on top of an
already-built :class:`SymbolIndex` -- the call graph already resolved
calls made from test files when that index was built, since tests are
ordinary Python modules to the AST parser.
"""

from pathlib import Path

from specwatch.code.python_parser import module_qualified_name
from specwatch.code.symbol_index import SymbolIndex, discover_python_files
from specwatch.domain.models import TestSymbol
from specwatch.tests_index.mapper import referenced_symbols_for_test
from specwatch.tests_index.pytest_parser import extract_test_symbols, is_test_file


class PytestIndex:
    """In-memory index of discovered pytest tests."""

    def __init__(self) -> None:
        self.tests: dict[str, TestSymbol] = {}

    def get(self, qualified_name: str) -> TestSymbol | None:
        return self.tests.get(qualified_name)

    def list(self) -> list[TestSymbol]:
        return list(self.tests.values())

    def tests_referencing(self, symbol_qualified_name: str) -> list[TestSymbol]:
        return [t for t in self.tests.values() if symbol_qualified_name in t.referenced_symbols]


def build_test_index(root: Path, symbol_index: SymbolIndex) -> PytestIndex:
    """Discover pytest tests under ``root`` and resolve their implementation
    references against an already-built ``symbol_index`` for the same root."""
    root = root.resolve()
    index = PytestIndex()

    for file_path in discover_python_files(root):
        if not is_test_file(file_path.name):
            continue
        try:
            source = file_path.read_text()
        except (UnicodeDecodeError, OSError):
            continue

        rel_path = file_path.relative_to(root)
        module_name = module_qualified_name(rel_path)
        rel_file = str(rel_path)
        try:
            tests = extract_test_symbols(source, file=rel_file, module_name=module_name)
        except SyntaxError:
            continue

        for test in tests:
            test.referenced_symbols = referenced_symbols_for_test(symbol_index, test.qualified_name)
            index.tests[test.qualified_name] = test

    return index
