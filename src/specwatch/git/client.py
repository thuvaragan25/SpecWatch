"""Thin subprocess wrapper around the ``git`` CLI.

No GitPython dependency -- the operations SpecWatch needs (diff,
name-status, show) are simple enough to shell out for directly, per
plan.md's Recommended Stack.
"""

import subprocess
from pathlib import Path


class GitError(Exception):
    """Raised when a git subprocess invocation fails."""


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def show_file_at_revision(repo: Path, revision: str, path: str) -> str | None:
    """Return a file's contents at ``revision``, or None if it doesn't exist there."""
    try:
        return run_git(["show", f"{revision}:{path}"], cwd=repo)
    except GitError:
        return None


def list_files_at_revision(repo: Path, revision: str) -> list[str]:
    """List every file path tracked at ``revision``, without checking it out."""
    output = run_git(["ls-tree", "-r", "--name-only", revision], cwd=repo)
    return [line for line in output.splitlines() if line.strip()]


def diff_name_status(repo: Path, base: str, head: str) -> list[dict]:
    """Parse ``git diff --name-status`` between ``base`` and the merge-base
    with ``head`` (triple-dot, matching a PR-style diff -- see plan.md §24).

    Returns a list of ``{"status", "path", "old_path"}`` dicts.
    """
    output = run_git(["diff", "--name-status", "-M", f"{base}...{head}"], cwd=repo)
    entries: list[dict] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            entries.append({"status": "R", "path": parts[2], "old_path": parts[1]})
        else:
            entries.append({"status": status, "path": parts[1], "old_path": None})
    return entries


def diff_unified(repo: Path, base: str, head: str, path: str) -> str:
    """Zero-context unified diff for one file -- hunk headers only carry
    exactly the changed line ranges, nothing else."""
    return run_git(
        ["diff", "--unified=0", f"{base}...{head}", "--", path], cwd=repo
    )


def diff_with_context(repo: Path, base: str, head: str, path: str, context_lines: int = 3) -> str:
    """Human/LLM-readable unified diff for one file, with surrounding
    context -- used for tool evidence display, not line-range parsing."""
    return run_git(
        ["diff", f"--unified={context_lines}", f"{base}...{head}", "--", path], cwd=repo
    )
