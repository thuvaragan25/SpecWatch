"""build_symbol_index_at_revision should see the repository exactly as it
was at a given revision, without needing that revision checked out --
this is what lets agent tools inspect "base" while the working tree
holds "head"."""

import subprocess
from pathlib import Path

import pytest

from specwatch.git.diff import build_symbol_index_at_revision


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def test_index_at_base_revision_differs_from_working_tree(temp_repo: Path) -> None:
    module = temp_repo / "service.py"
    module.write_text("def send(x):\n    return x\n")
    _git(temp_repo, "add", "service.py")
    _git(temp_repo, "commit", "-q", "-m", "base")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=temp_repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    module.write_text("def send(x):\n    return x\n\n\ndef receive(x):\n    return x\n")
    _git(temp_repo, "commit", "-q", "-am", "head")

    base_index = build_symbol_index_at_revision(temp_repo, base_sha)
    assert base_index.get("service.send") is not None
    assert base_index.get("service.receive") is None  # doesn't exist yet at base


def test_index_at_revision_does_not_require_checkout(temp_repo: Path) -> None:
    module = temp_repo / "a.py"
    module.write_text("def helper():\n    pass\n")
    _git(temp_repo, "add", "a.py")
    _git(temp_repo, "commit", "-q", "-m", "only commit")

    # working tree is at HEAD; ask for HEAD explicitly via git show anyway
    index = build_symbol_index_at_revision(temp_repo, "HEAD")
    assert index.get("a.helper") is not None
