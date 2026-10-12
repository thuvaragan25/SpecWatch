"""Extraction of pytest test functions from a single module.

A test's ``fixtures`` list is simply its parameter names -- in pytest,
every test parameter is a fixture request, so enumerating them needs no
fixture *resolution* (what a fixture actually provides). Deeper
fixture/mock parsing is out of scope for V1 (see plan.md Review Addendum).
"""

import ast

from specwatch.domain.models import SourceLocation, TestSymbol

_ASSERTION_LIMIT = 20


def is_test_file(file_name: str) -> bool:
    return file_name.startswith("test_") or file_name.endswith("_test.py")


def extract_test_symbols(source: str, file: str, module_name: str) -> list[TestSymbol]:
    """Extract top-level ``test_*`` functions and methods on ``Test*`` classes."""
    tree = ast.parse(source, filename=file)
    tests: list[TestSymbol] = []

    for node in tree.body:
        if _is_test_function(node):
            tests.append(_build_test_symbol(node, f"{module_name}.{node.name}", file))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for child in node.body:
                if _is_test_function(child):
                    tests.append(
                        _build_test_symbol(child, f"{module_name}.{node.name}.{child.name}", file)
                    )
    return tests


def _is_test_function(node: ast.stmt) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")


def _build_test_symbol(
    node: ast.FunctionDef | ast.AsyncFunctionDef, qualified_name: str, file: str
) -> TestSymbol:
    fixtures = [arg.arg for arg in node.args.args if arg.arg not in ("self", "cls")]
    return TestSymbol(
        qualified_name=qualified_name,
        name=node.name,
        file=file,
        source=SourceLocation(
            file=file, line_start=node.lineno, line_end=node.end_lineno or node.lineno
        ),
        docstring=ast.get_docstring(node),
        fixtures=fixtures,
        assertions=_extract_assertions(node),
    )


def _extract_assertions(node: ast.AST) -> list[str]:
    assertions: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            try:
                assertions.append(ast.unparse(child.test))
            except Exception:  # noqa: BLE001 - best-effort static analysis
                continue
            if len(assertions) >= _ASSERTION_LIMIT:
                break
    return assertions
