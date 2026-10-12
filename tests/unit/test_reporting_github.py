import json
from pathlib import Path

from specwatch.reporting.github import (
    find_existing_comment_id,
    post_or_update_pr_comment,
    pr_number_from_github_event,
    write_job_summary,
)


class _RecordingHttpCaller:
    """Fake HTTP caller: records every call and returns scripted responses,
    so request-building logic is tested without any real network access."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict, dict | None]] = []

    def __call__(self, method: str, url: str, headers: dict, body: dict | None) -> object:
        self.calls.append((method, url, headers, body))
        return self.responses.get(method, [])


def test_write_job_summary_appends_to_explicit_path(tmp_path: Path) -> None:
    path = tmp_path / "summary.md"
    path.write_text("existing content\n")

    write_job_summary("new markdown", summary_path=path)

    content = path.read_text()
    assert "existing content" in content
    assert "new markdown" in content


def test_write_job_summary_is_noop_without_path_or_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    write_job_summary("markdown")  # must not raise


def test_find_existing_comment_id_returns_none_when_no_marker_present() -> None:
    caller = _RecordingHttpCaller({"GET": [{"id": 1, "body": "unrelated comment"}]})
    result = find_existing_comment_id("owner/repo", 42, "tok", http_caller=caller)
    assert result is None
    assert caller.calls[0][0] == "GET"
    assert "owner/repo" in caller.calls[0][1]
    assert "42" in caller.calls[0][1]


def test_find_existing_comment_id_finds_marked_comment() -> None:
    caller = _RecordingHttpCaller(
        {"GET": [{"id": 7, "body": "<!-- specwatch-finding-comment -->\nold content"}]}
    )
    result = find_existing_comment_id("owner/repo", 42, "tok", http_caller=caller)
    assert result == 7


def test_post_or_update_creates_comment_when_none_exists() -> None:
    caller = _RecordingHttpCaller({"GET": []})
    post_or_update_pr_comment("owner/repo", 42, "tok", "some findings", http_caller=caller)

    methods = [call[0] for call in caller.calls]
    assert methods == ["GET", "POST"]
    post_call = caller.calls[1]
    assert post_call[1].endswith("/repos/owner/repo/issues/42/comments")
    assert "some findings" in post_call[3]["body"]
    assert "specwatch-finding-comment" in post_call[3]["body"]


def test_post_or_update_patches_existing_comment_instead_of_creating_new() -> None:
    caller = _RecordingHttpCaller(
        {"GET": [{"id": 99, "body": "<!-- specwatch-finding-comment -->\nold"}]}
    )
    post_or_update_pr_comment("owner/repo", 42, "tok", "new findings", http_caller=caller)

    methods = [call[0] for call in caller.calls]
    assert methods == ["GET", "PATCH"]
    patch_call = caller.calls[1]
    assert patch_call[1].endswith("/repos/owner/repo/issues/comments/99")
    assert "new findings" in patch_call[3]["body"]


def test_post_or_update_includes_auth_header() -> None:
    caller = _RecordingHttpCaller({"GET": []})
    post_or_update_pr_comment("owner/repo", 1, "secret-token", "x", http_caller=caller)
    for call in caller.calls:
        assert call[2]["Authorization"] == "Bearer secret-token"


def test_pr_number_from_github_event_reads_pull_request_number(tmp_path: Path, monkeypatch) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"pull_request": {"number": 123}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    assert pr_number_from_github_event() == 123


def test_pr_number_from_github_event_returns_none_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert pr_number_from_github_event() is None


def test_pr_number_from_github_event_returns_none_for_non_pr_event(tmp_path: Path, monkeypatch) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"ref": "refs/heads/main"}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    assert pr_number_from_github_event() is None
