"""SQLite connection and schema management."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    passage_type TEXT NOT NULL,
    status TEXT NOT NULL,
    source_file TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS requirement_candidates (
    requirement_id TEXT NOT NULL,
    symbol_qualified_name TEXT NOT NULL,
    score REAL NOT NULL,
    method TEXT NOT NULL,
    PRIMARY KEY (requirement_id, symbol_qualified_name)
);

CREATE INDEX IF NOT EXISTS idx_requirement_candidates_symbol
    ON requirement_candidates (symbol_qualified_name);

CREATE TABLE IF NOT EXISTS test_candidates (
    requirement_id TEXT NOT NULL,
    test_qualified_name TEXT NOT NULL,
    score REAL NOT NULL,
    method TEXT NOT NULL,
    PRIMARY KEY (requirement_id, test_qualified_name)
);
"""


def default_db_path(repo_path: Path) -> Path:
    """The default SpecWatch database location for a repository."""
    return repo_path / ".specwatch" / "specwatch.db"


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) a SpecWatch SQLite database with schema applied."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
