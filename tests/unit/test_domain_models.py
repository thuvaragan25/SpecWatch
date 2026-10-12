import pytest

from specwatch.domain.models import SourceLocation


def test_source_location_valid_range() -> None:
    loc = SourceLocation(file="a.py", line_start=1, line_end=3)
    assert loc.line_end == 3


def test_source_location_rejects_inverted_range() -> None:
    with pytest.raises(ValueError):
        SourceLocation(file="a.py", line_start=5, line_end=1)


def test_source_location_single_line_is_valid() -> None:
    loc = SourceLocation(file="a.py", line_start=4, line_end=4)
    assert loc.line_start == loc.line_end == 4
