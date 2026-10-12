from specwatch.git.diff import _parse_hunk_line_ranges


def test_parses_pure_addition_hunk() -> None:
    diff_text = "@@ -3,0 +4,2 @@\n+line a\n+line b\n"
    added, removed = _parse_hunk_line_ranges(diff_text)
    assert added == [4, 5]
    assert removed == []


def test_parses_pure_removal_hunk() -> None:
    diff_text = "@@ -4,2 +3,0 @@\n-line a\n-line b\n"
    added, removed = _parse_hunk_line_ranges(diff_text)
    assert added == []
    assert removed == [4, 5]


def test_parses_single_line_replacement_hunk() -> None:
    diff_text = "@@ -2 +2 @@\n-old\n+new\n"
    added, removed = _parse_hunk_line_ranges(diff_text)
    assert added == [2]
    assert removed == [2]


def test_parses_multiple_hunks() -> None:
    diff_text = "@@ -1 +1 @@\n-a\n+b\n@@ -10,2 +10,2 @@\n-c\n-d\n+e\n+f\n"
    added, removed = _parse_hunk_line_ranges(diff_text)
    assert added == [1, 10, 11]
    assert removed == [1, 10, 11]


def test_no_hunks_returns_empty() -> None:
    assert _parse_hunk_line_ranges("") == ([], [])
