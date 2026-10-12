"""Markdown rendering of verified findings for GitHub job summaries and
PR comments.

Renders only what the pipeline actually retains past verification
(verdict, summary, reasoning, citations, confidence) -- plan.md §22's
example PR comment also shows a per-tool investigation checklist, which
would need tool_history threaded through run_analysis's return type.
Left out of V1.1 as a presentation-only gap, not a correctness one.
"""

from specwatch.verification.verifier import VerificationResult

_CONFIDENCE_LABELS = [(0.9, "Very High"), (0.8, "High"), (0.6, "Medium")]


def _confidence_label(score: float) -> str:
    for threshold, label in _CONFIDENCE_LABELS:
        if score >= threshold:
            return label
    return "Low"


def render_findings_markdown(results: list[VerificationResult]) -> str:
    published = [r for r in results if r.decision == "publish"]
    if not published:
        return "**SpecWatch**\n\nNo specification drift findings for this change.\n"

    lines = ["**SpecWatch**", "", f"{len(published)} possible specification conflict(s) found.", ""]
    for result in published:
        finding = result.finding
        lines.append(f"### {finding.verdict.value.replace('_', ' ').title()}")
        if finding.requirement_ids:
            lines.append(f"Requirement(s): {', '.join(finding.requirement_ids)}")
        lines.append("")
        lines.append(finding.summary)
        lines.append("")
        if finding.reasoning:
            lines.append(f"**Investigation:** {finding.reasoning}")
            lines.append("")
        if finding.citations:
            lines.append("**Evidence:**")
            for citation in finding.citations:
                lines.append(f"- `{citation.file}:{citation.line_start}-{citation.line_end}`")
            lines.append("")
        if finding.unresolved_questions:
            lines.append("**Unresolved questions:**")
            for question in finding.unresolved_questions:
                lines.append(f"- {question}")
            lines.append("")
        lines.append(
            f"**Confidence:** {_confidence_label(result.computed_confidence)} "
            f"({result.computed_confidence:.2f})"
        )
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
