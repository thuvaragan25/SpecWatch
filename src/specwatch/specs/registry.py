"""Stable requirement ID generation.

IDs are a fingerprint of document identity + heading + normalized
statement text -- never of line numbers -- so edits elsewhere in a
document (adding a paragraph above, reordering sections) never change an
existing requirement's ID.
"""

import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip().lower())


def stable_requirement_id(document: str, heading: str, statement: str) -> str:
    """Derive a stable ``REQ-XXXXXX`` fingerprint ID."""
    fingerprint_input = "\x1f".join(
        [_normalize(document), _normalize(heading), _normalize(statement)]
    )
    digest = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()
    return f"REQ-{digest[:6].upper()}"
