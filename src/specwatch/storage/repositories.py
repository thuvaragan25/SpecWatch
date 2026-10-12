"""Repository classes mediating between domain models and SQLite."""

import sqlite3

from specwatch.domain.enums import CandidateMethod, PassageType, RequirementStatus
from specwatch.domain.models import Requirement, RequirementCandidate, SourceLocation, RequirementTestCandidate


class RequirementRepository:
    """Persists and retrieves :class:`Requirement` records."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, requirement: Requirement) -> None:
        self._conn.execute(
            """
            INSERT INTO requirements
                (id, title, statement, passage_type, status, source_file, line_start, line_end)
            VALUES
                (:id, :title, :statement, :passage_type, :status, :source_file, :line_start, :line_end)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                statement=excluded.statement,
                passage_type=excluded.passage_type,
                status=excluded.status,
                source_file=excluded.source_file,
                line_start=excluded.line_start,
                line_end=excluded.line_end
            """,
            {
                "id": requirement.id,
                "title": requirement.title,
                "statement": requirement.statement,
                "passage_type": requirement.passage_type.value,
                "status": requirement.status.value,
                "source_file": requirement.source.file,
                "line_start": requirement.source.line_start,
                "line_end": requirement.source.line_end,
            },
        )
        self._conn.commit()

    def save_all(self, requirements: list[Requirement]) -> None:
        for requirement in requirements:
            self.save(requirement)

    def get(self, requirement_id: str) -> Requirement | None:
        row = self._conn.execute(
            "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
        ).fetchone()
        return _row_to_requirement(row) if row else None

    def list(self, status: RequirementStatus | None = None) -> list[Requirement]:
        if status is None:
            rows = self._conn.execute("SELECT * FROM requirements ORDER BY id").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM requirements WHERE status = ? ORDER BY id", (status.value,)
            ).fetchall()
        return [_row_to_requirement(row) for row in rows]


class CandidateRepository:
    """Persists requirement<->code and requirement<->test candidate links.

    Candidates are recomputed on every index run (see plan.md's Evidence
    Graph Review Addendum), so writes replace a requirement's full
    candidate set rather than upserting individual rows.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def replace_symbol_candidates(
        self, requirement_id: str, candidates: list[RequirementCandidate]
    ) -> None:
        self._conn.execute(
            "DELETE FROM requirement_candidates WHERE requirement_id = ?", (requirement_id,)
        )
        self._conn.executemany(
            """
            INSERT INTO requirement_candidates
                (requirement_id, symbol_qualified_name, score, method)
            VALUES (?, ?, ?, ?)
            """,
            [
                (c.requirement_id, c.symbol_qualified_name, c.score, c.method.value)
                for c in candidates
            ],
        )
        self._conn.commit()

    def replace_test_candidates(self, requirement_id: str, candidates: list[RequirementTestCandidate]) -> None:
        self._conn.execute("DELETE FROM test_candidates WHERE requirement_id = ?", (requirement_id,))
        self._conn.executemany(
            """
            INSERT INTO test_candidates
                (requirement_id, test_qualified_name, score, method)
            VALUES (?, ?, ?, ?)
            """,
            [(c.requirement_id, c.test_qualified_name, c.score, c.method.value) for c in candidates],
        )
        self._conn.commit()

    def symbol_candidates_for_requirement(self, requirement_id: str) -> list[RequirementCandidate]:
        rows = self._conn.execute(
            "SELECT * FROM requirement_candidates WHERE requirement_id = ? ORDER BY score DESC",
            (requirement_id,),
        ).fetchall()
        return [_row_to_requirement_candidate(row) for row in rows]

    def test_candidates_for_requirement(self, requirement_id: str) -> list[RequirementTestCandidate]:
        rows = self._conn.execute(
            "SELECT * FROM test_candidates WHERE requirement_id = ? ORDER BY score DESC",
            (requirement_id,),
        ).fetchall()
        return [_row_to_test_candidate(row) for row in rows]

    def requirements_for_symbol(self, symbol_qualified_name: str) -> list[RequirementCandidate]:
        """Reverse lookup used by the impact filter: given a changed
        symbol, which requirements might it be relevant to?"""
        rows = self._conn.execute(
            "SELECT * FROM requirement_candidates WHERE symbol_qualified_name = ? ORDER BY score DESC",
            (symbol_qualified_name,),
        ).fetchall()
        return [_row_to_requirement_candidate(row) for row in rows]


def _row_to_requirement_candidate(row: sqlite3.Row) -> RequirementCandidate:
    return RequirementCandidate(
        requirement_id=row["requirement_id"],
        symbol_qualified_name=row["symbol_qualified_name"],
        score=row["score"],
        method=CandidateMethod(row["method"]),
    )


def _row_to_test_candidate(row: sqlite3.Row) -> RequirementTestCandidate:
    return RequirementTestCandidate(
        requirement_id=row["requirement_id"],
        test_qualified_name=row["test_qualified_name"],
        score=row["score"],
        method=CandidateMethod(row["method"]),
    )


def _row_to_requirement(row: sqlite3.Row) -> Requirement:
    return Requirement(
        id=row["id"],
        title=row["title"],
        statement=row["statement"],
        passage_type=PassageType(row["passage_type"]),
        status=RequirementStatus(row["status"]),
        source=SourceLocation(
            file=row["source_file"],
            line_start=row["line_start"],
            line_end=row["line_end"],
        ),
    )
