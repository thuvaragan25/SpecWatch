"""GitHub job summary and PR comment posting.

The HTTP call is isolated behind an injectable `http_caller`, so the
request-building logic (URLs, methods, payloads, update-vs-create
decision) is fully unit-testable without a live GitHub API -- there is
no way to exercise a real GitHub API call in this environment, so tests
inject a fake caller and assert on what would have been sent.
"""

import json
import os
import urllib.request
from pathlib import Path
from typing import Callable

_COMMENT_MARKER = "<!-- specwatch-finding-comment -->"

HttpCaller = Callable[[str, str, dict, dict | None], object]


def default_http_caller(method: str, url: str, headers: dict, body: dict | None) -> object:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request) as response:  # noqa: S310 - GitHub API only
        raw = response.read()
        return json.loads(raw) if raw else None


def write_job_summary(markdown: str, summary_path: Path | None = None) -> None:
    """Append to $GITHUB_STEP_SUMMARY (or an explicit path for tests). A
    no-op outside CI, where that env var isn't set."""
    path = summary_path
    if path is None:
        env_path = os.environ.get("GITHUB_STEP_SUMMARY")
        path = Path(env_path) if env_path else None
    if path is None:
        return
    with path.open("a") as f:
        f.write(markdown)
        f.write("\n")


def find_existing_comment_id(
    repo: str, pr_number: int, token: str, http_caller: HttpCaller = default_http_caller
) -> int | None:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    comments = http_caller("GET", url, headers, None)
    for comment in comments if isinstance(comments, list) else []:
        if _COMMENT_MARKER in comment.get("body", ""):
            return comment["id"]
    return None


def post_or_update_pr_comment(
    repo: str, pr_number: int, token: str, markdown: str, http_caller: HttpCaller = default_http_caller
) -> None:
    """Create the summary comment if none exists yet, else update it in
    place -- never post a new comment on every run (plan.md §24: "prefer
    a single summary comment initially")."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    body_text = f"{_COMMENT_MARKER}\n{markdown}"
    existing_id = find_existing_comment_id(repo, pr_number, token, http_caller)
    if existing_id is not None:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        http_caller("PATCH", url, headers, {"body": body_text})
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        http_caller("POST", url, headers, {"body": body_text})


def pr_number_from_github_event() -> int | None:
    """Read the PR number from $GITHUB_EVENT_PATH, the JSON file GitHub
    Actions provides for pull_request-triggered workflows."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        event = json.loads(Path(event_path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return None
    number = pull_request.get("number")
    return number if isinstance(number, int) else None
