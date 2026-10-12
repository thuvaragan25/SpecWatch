"""inspect_git_history.

Bounded, stat-only commit history -- commit sha, subject line, and a
single file's diffstat -- never full patches. Useful for disambiguating
whether a suspicious change was an intentional refactor/relocation
rather than a dropped behavior.
"""

from pathlib import Path

from pydantic import BaseModel

from specwatch.agent.tools.context import MAX_COMMIT_HISTORY_LIMIT, ToolContext
from specwatch.git.client import run_git


class CommitSummary(BaseModel):
    sha: str
    message: str
    stat: str


def inspect_git_history(
    context: ToolContext,
    symbol: str | None = None,
    file: str | None = None,
    limit: int = 5,
) -> list[CommitSummary]:
    """History for ``file``, or for the file currently containing
    ``symbol`` (head, falling back to base) if ``file`` isn't given."""
    limit = max(1, min(limit, MAX_COMMIT_HISTORY_LIMIT))

    if file is None and symbol is not None:
        target = context.head_symbol_index.get(symbol) or context.base_symbol_index.get(symbol)
        file = target.file if target is not None else None

    if file is None:
        return []

    commits = _list_commits(context.repo, context.head, file, limit)
    return [
        CommitSummary(sha=sha, message=subject, stat=_commit_stat(context.repo, sha, file))
        for sha, subject in commits
    ]


def _list_commits(repo: Path, revision: str, file: str, limit: int) -> list[tuple[str, str]]:
    output = run_git(
        ["log", f"-{limit}", "--follow", "--pretty=format:%H%x1f%s", revision, "--", file],
        cwd=repo,
    )
    commits: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\x1f")
        commits.append((sha, subject))
    return commits


def _commit_stat(repo: Path, sha: str, file: str) -> str:
    output = run_git(["show", "--stat", "--format=", sha, "--", file], cwd=repo)
    return output.strip()
