"""search_requirements, inspect_requirement.

search_requirements returns short hits only (id/title/source/snippet/
score) -- inspect_requirement is the only tool that returns a
requirement's full statement text, keeping search results bounded.
"""

from pydantic import BaseModel

from specwatch.agent.tools.context import MAX_SEARCH_LIMIT, ToolContext, truncate_text
from specwatch.domain.enums import PassageType, RequirementStatus
from specwatch.domain.models import SourceLocation
from specwatch.mapping.candidate_generator import BM25Index, Document


class RequirementHit(BaseModel):
    requirement_id: str
    title: str
    source: SourceLocation
    snippet: str
    score: float


class RequirementDetail(BaseModel):
    requirement_id: str
    title: str
    statement: str
    passage_type: PassageType
    status: RequirementStatus
    source: SourceLocation


def search_requirements(context: ToolContext, query: str, limit: int = 10) -> list[RequirementHit]:
    """Lexical (BM25) search over active requirement titles/statements."""
    limit = min(limit, MAX_SEARCH_LIMIT)
    requirements = [
        r for r in context.requirement_repo.list() if r.status == RequirementStatus.ACTIVE
    ]
    documents = [Document(id=r.id, text=f"{r.title} {r.statement}") for r in requirements]
    by_id = {r.id: r for r in requirements}

    index = BM25Index(documents)
    hits: list[RequirementHit] = []
    for requirement_id, score in index.search(query, limit=limit):
        requirement = by_id[requirement_id]
        hits.append(
            RequirementHit(
                requirement_id=requirement.id,
                title=requirement.title,
                source=requirement.source,
                snippet=truncate_text(requirement.statement),
                score=score,
            )
        )
    return hits


def inspect_requirement(context: ToolContext, requirement_id: str) -> RequirementDetail | None:
    """Full detail for one requirement, or None if the ID doesn't exist."""
    requirement = context.requirement_repo.get(requirement_id)
    if requirement is None:
        return None
    return RequirementDetail(
        requirement_id=requirement.id,
        title=requirement.title,
        statement=requirement.statement,
        passage_type=requirement.passage_type,
        status=requirement.status,
        source=requirement.source,
    )
