"""Citation validation: the primary anti-hallucination gate.

A citation is valid only if:
1. its evidence_id references an EvidenceItem actually retrieved this
   investigation (not a plausible-sounding ID the model invented)
2. that evidence's recorded content actually mentions the cited file
   (the agent must have actually looked at it, not merely know it exists)
3. the cited quote is real text, found within [line_start, line_end] of
   that file at head, base, or on disk -- whichever is retrievable

Any single failure invalidates the WHOLE finding, not just the bad
citation -- fail closed (see verification.verifier).
"""

from dataclasses import dataclass
from pathlib import Path

from specwatch.agent.state import EvidenceItem
from specwatch.agent.tools.context import ToolContext
from specwatch.domain.models import Citation


@dataclass(frozen=True)
class CitationIssue:
    citation: Citation
    reason: str


def validate_citations(
    citations: list[Citation], evidence_items: list[EvidenceItem], context: ToolContext
) -> list[CitationIssue]:
    evidence_by_id = {item.id: item for item in evidence_items}
    issues: list[CitationIssue] = []

    for citation in citations:
        evidence = evidence_by_id.get(citation.evidence_id)
        if evidence is None:
            issues.append(
                CitationIssue(citation, f"evidence_id {citation.evidence_id!r} was not retrieved this investigation")
            )
            continue

        if citation.file not in evidence.content:
            issues.append(
                CitationIssue(
                    citation,
                    f"cited file {citation.file!r} does not appear in evidence {citation.evidence_id!r}",
                )
            )
            continue

        if not _quote_matches_source(context, citation):
            issues.append(CitationIssue(citation, "cited quote was not found in the cited line range"))

    return issues


def _quote_matches_source(context: ToolContext, citation: Citation) -> bool:
    quote = citation.quote.strip()
    if not quote:
        return False
    for source in _candidate_sources(context, citation.file):
        lines = source.splitlines()
        start = max(citation.line_start - 1, 0)
        end = min(citation.line_end, len(lines))
        window = "\n".join(lines[start:end])
        if quote in window:
            return True
    return False


def _candidate_sources(context: ToolContext, file: str) -> list[str]:
    """Every plausible source of ``file``'s content -- head, base, and a
    direct filesystem read (covers spec files outside git's base/head
    comparison, e.g. an externally-passed --spec path)."""
    sources: list[str] = []
    for revision in ("head", "base"):
        source = context.read_source(revision, file)
        if source is not None:
            sources.append(source)
    try:
        disk_path = Path(file)
        if not disk_path.is_absolute():
            disk_path = context.repo / disk_path
        sources.append(disk_path.read_text())
    except OSError:
        pass
    return sources
