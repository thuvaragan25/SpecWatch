"""Deterministic passage classification and requirement extraction.

V1 classifies passages with heading-keyword and modal-verb heuristics
rather than an LLM call, keeping requirement extraction fully offline and
deterministic (see plan.md Review Addendum). LLM-assisted classification
for ambiguous cases is a natural later upgrade, not a V1 requirement.
"""

import re

from specwatch.domain.enums import PassageType, RequirementStatus
from specwatch.domain.models import Requirement, SourceLocation
from specwatch.specs.parser import Section, segment_markdown
from specwatch.specs.registry import stable_requirement_id

_EXTRACTABLE_TYPES = {PassageType.REQUIREMENT, PassageType.ARCHITECTURE_RULE}

_MODAL_RE = re.compile(r"\b(must|shall|required to|may not|must not|should)\b", re.IGNORECASE)
_NON_GOAL_HEADING_RE = re.compile(r"non[- ]goals?", re.IGNORECASE)
_OUT_OF_SCOPE_HEADING_RE = re.compile(r"out of scope", re.IGNORECASE)
_EXAMPLE_HEADING_RE = re.compile(r"example", re.IGNORECASE)
_RATIONALE_HEADING_RE = re.compile(r"rationale|motivation", re.IGNORECASE)
_ARCHITECTURE_HEADING_RE = re.compile(r"architecture|layering|design constraint", re.IGNORECASE)

_STATEMENT_MAX_LENGTH = 2000


def classify_section(section: Section) -> PassageType:
    """Classify a section by heading keywords, falling back to modal-verb
    detection in the body for plain requirement statements."""
    heading = section.heading
    if _NON_GOAL_HEADING_RE.search(heading):
        return PassageType.NON_GOAL
    if _OUT_OF_SCOPE_HEADING_RE.search(heading):
        return PassageType.OUT_OF_SCOPE
    if _EXAMPLE_HEADING_RE.search(heading):
        return PassageType.EXAMPLE
    if _RATIONALE_HEADING_RE.search(heading):
        return PassageType.DESIGN_RATIONALE
    if _ARCHITECTURE_HEADING_RE.search(heading):
        return PassageType.ARCHITECTURE_RULE
    if _MODAL_RE.search(section.body):
        return PassageType.REQUIREMENT
    return PassageType.CONTEXT


def extract_requirements(text: str, source_file: str) -> list[Requirement]:
    """Segment, classify, and extract requirements/architecture rules from
    a Markdown spec document."""
    requirements: list[Requirement] = []
    for section in segment_markdown(text):
        passage_type = classify_section(section)
        if passage_type not in _EXTRACTABLE_TYPES:
            continue
        if not section.body.strip():
            continue

        statement = _normalize_statement(section.body)
        requirement_id = stable_requirement_id(
            document=source_file, heading=section.heading, statement=statement
        )
        requirements.append(
            Requirement(
                id=requirement_id,
                title=section.heading,
                statement=statement,
                passage_type=passage_type,
                status=RequirementStatus.ACTIVE,
                source=SourceLocation(
                    file=source_file,
                    line_start=section.line_start,
                    line_end=section.line_end,
                ),
            )
        )
    return requirements


def _normalize_statement(body: str) -> str:
    collapsed = " ".join(body.split())
    return collapsed[:_STATEMENT_MAX_LENGTH]
