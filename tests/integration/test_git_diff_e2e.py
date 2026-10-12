"""Phase 5 acceptance: `specwatch diff` correctly identifies changed files
and changed symbols between base and head, on a real temporary git
repository (see plan.md's End-to-End Testing Strategy)."""

import subprocess
from pathlib import Path

import pytest

from specwatch.domain.enums import FileChangeType, SymbolChangeType
from specwatch.git.diff import changed_files, changed_symbols


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def test_modified_function_is_detected(temp_repo: Path) -> None:
    module = temp_repo / "service.py"
    module.write_text("def send(x):\n    return x\n")
    _git(temp_repo, "add", "service.py")
    _git(temp_repo, "commit", "-q", "-m", "base")

    module.write_text("def send(x):\n    return x + 1\n")
    _git(temp_repo, "commit", "-q", "-am", "head")

    files = changed_files(temp_repo, "HEAD~1", "HEAD")
    assert len(files) == 1
    assert files[0].path == "service.py"
    assert files[0].change_type == FileChangeType.MODIFIED
    assert files[0].added_lines == [2]
    assert files[0].removed_lines == [2]

    symbols = changed_symbols(temp_repo, "HEAD~1", "HEAD", temp_repo)
    assert len(symbols) == 1
    assert symbols[0].qualified_name == "service.send"
    assert symbols[0].change_type == SymbolChangeType.MODIFIED


def test_whitespace_only_change_does_not_register_as_symbol_change(temp_repo: Path) -> None:
    module = temp_repo / "service.py"
    module.write_text("def send(x):\n    return x\n")
    _git(temp_repo, "add", "service.py")
    _git(temp_repo, "commit", "-q", "-m", "base")

    module.write_text("def send(x):\n\n    return x   \n")
    _git(temp_repo, "commit", "-q", "-am", "head")

    files = changed_files(temp_repo, "HEAD~1", "HEAD")
    assert len(files) == 1  # the file did change

    symbols = changed_symbols(temp_repo, "HEAD~1", "HEAD", temp_repo)
    assert symbols == []  # but no symbol's actual behavior changed


def test_added_function_is_detected(temp_repo: Path) -> None:
    module = temp_repo / "service.py"
    module.write_text("def send(x):\n    return x\n")
    _git(temp_repo, "add", "service.py")
    _git(temp_repo, "commit", "-q", "-m", "base")

    module.write_text("def send(x):\n    return x\n\n\ndef receive(x):\n    return x\n")
    _git(temp_repo, "commit", "-q", "-am", "head")

    symbols = changed_symbols(temp_repo, "HEAD~1", "HEAD", temp_repo)
    assert len(symbols) == 1
    assert symbols[0].qualified_name == "service.receive"
    assert symbols[0].change_type == SymbolChangeType.ADDED
    assert symbols[0].base_symbol is None
    assert symbols[0].head_symbol is not None


def test_removed_function_is_detected(temp_repo: Path) -> None:
    module = temp_repo / "service.py"
    module.write_text("def send(x):\n    return x\n\n\ndef receive(x):\n    return x\n")
    _git(temp_repo, "add", "service.py")
    _git(temp_repo, "commit", "-q", "-m", "base")

    module.write_text("def send(x):\n    return x\n")
    _git(temp_repo, "commit", "-q", "-am", "head")

    symbols = changed_symbols(temp_repo, "HEAD~1", "HEAD", temp_repo)
    assert len(symbols) == 1
    assert symbols[0].qualified_name == "service.receive"
    assert symbols[0].change_type == SymbolChangeType.REMOVED
    assert symbols[0].head_symbol is None


def test_renamed_file_is_detected(temp_repo: Path) -> None:
    module = temp_repo / "service.py"
    module.write_text("def send(x):\n    return x\n")
    _git(temp_repo, "add", "service.py")
    _git(temp_repo, "commit", "-q", "-m", "base")

    new_module = temp_repo / "delivery.py"
    module.rename(new_module)
    _git(temp_repo, "add", "-A")
    _git(temp_repo, "commit", "-q", "-m", "rename")

    files = changed_files(temp_repo, "HEAD~1", "HEAD")
    assert len(files) == 1
    assert files[0].change_type == FileChangeType.RENAMED
    assert files[0].path == "delivery.py"
    assert files[0].old_path == "service.py"


def test_new_file_reports_only_additions(temp_repo: Path) -> None:
    (temp_repo / "a.py").write_text("x = 1\n")
    _git(temp_repo, "add", "a.py")
    _git(temp_repo, "commit", "-q", "-m", "base")

    (temp_repo / "b.py").write_text("def helper():\n    pass\n")
    _git(temp_repo, "add", "b.py")
    _git(temp_repo, "commit", "-q", "-m", "add file")

    files = changed_files(temp_repo, "HEAD~1", "HEAD")
    assert len(files) == 1
    assert files[0].change_type == FileChangeType.ADDED
    assert files[0].removed_lines == []
    assert files[0].added_lines == [1, 2]


def test_non_python_files_are_ignored(temp_repo: Path) -> None:
    (temp_repo / "a.py").write_text("x = 1\n")
    _git(temp_repo, "add", "a.py")
    _git(temp_repo, "commit", "-q", "-m", "base")

    (temp_repo / "README.md").write_text("# hello\n")
    _git(temp_repo, "add", "README.md")
    _git(temp_repo, "commit", "-q", "-m", "docs")

    assert changed_files(temp_repo, "HEAD~1", "HEAD") == []
