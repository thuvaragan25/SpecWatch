"""Markdown section segmentation.

Segments a Markdown document by ATX headings (``#`` .. ``######``). Each
section's ``body`` is only the text immediately following its heading, up
to the *next* heading of any level -- not the text of nested subsections.
This keeps leaf sections (e.g. a single requirement under ``###``) tightly
scoped, and container sections (e.g. a ``##`` category wrapping several
``###`` requirements) from swallowing all of their children's text.
"""

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.*)$")


@dataclass(frozen=True)
class Section:
    """One heading and its immediately-following body text."""

    heading: str
    level: int
    body: str
    line_start: int
    line_end: int


def segment_markdown(text: str) -> list[Section]:
    """Split ``text`` into sections at each ATX heading line."""
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match:
            headings.append((i, len(match.group(1)), match.group(2).strip()))

    sections: list[Section] = []
    for idx, (line_index, level, heading_text) in enumerate(headings):
        end_index = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        body_lines = lines[line_index + 1 : end_index]
        line_end = _last_content_line(body_lines, body_start=line_index + 2, heading_line=line_index + 1)
        body = "\n".join(body_lines).strip("\n")
        sections.append(
            Section(
                heading=heading_text,
                level=level,
                body=body,
                line_start=line_index + 1,
                line_end=line_end,
            )
        )
    return sections


def _last_content_line(body_lines: list[str], body_start: int, heading_line: int) -> int:
    """Return the 1-indexed line number of the last non-blank body line."""
    for offset in range(len(body_lines) - 1, -1, -1):
        if body_lines[offset].strip():
            return body_start + offset
    return heading_line
