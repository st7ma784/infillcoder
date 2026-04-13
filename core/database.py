"""
InfillCode SQLite database operations.

Schema:
    files  — one row per encoded GCode file
    layers — one row per layer attempt (encoded or skipped)

This module is stateless; callers pass a connection or path.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS files (
    file_id            INTEGER PRIMARY KEY,
    gcode_sha256       TEXT    NOT NULL UNIQUE,
    filename           TEXT    NOT NULL,
    total_layers       INTEGER,
    nominal_spacing_mm REAL,
    created_at         TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS layers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    layer_idx           INTEGER NOT NULL,
    z_height_mm         REAL    NOT NULL,
    line_count          INTEGER NOT NULL,
    encoded             INTEGER NOT NULL CHECK (encoded IN (0, 1)),
    payload_bits        INTEGER,
    correlated_payload  INTEGER,
    cumulative_e_mm     REAL,
    time_estimate_s     INTEGER,
    skip_reason         TEXT,
    UNIQUE(file_id, layer_idx)
);

CREATE INDEX IF NOT EXISTS idx_layers_payload
    ON layers(payload_bits)
    WHERE payload_bits IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_layers_correlated
    ON layers(correlated_payload)
    WHERE correlated_payload IS NOT NULL;

CREATE VIEW IF NOT EXISTS layer_summary AS
    SELECT f.filename,
           l.layer_idx,
           l.z_height_mm,
           l.encoded,
           l.cumulative_e_mm,
           l.time_estimate_s,
           ROUND(100.0 * l.layer_idx / f.total_layers, 1) AS pct_complete
    FROM layers l
    JOIN files f ON l.file_id = f.file_id;
"""


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (or create) a database at *path* and apply the schema."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.commit()
    return conn


def open_memory_db() -> sqlite3.Connection:
    """Return an in-memory database (useful for tests)."""
    return open_db(":memory:")


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context manager that commits or rolls back."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def insert_file(
    conn: sqlite3.Connection,
    file_id: int,
    gcode_sha256: str,
    filename: str,
    total_layers: Optional[int] = None,
    nominal_spacing_mm: Optional[float] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO files (file_id, gcode_sha256, filename, total_layers, nominal_spacing_mm)
        VALUES (?, ?, ?, ?, ?)
        """,
        (file_id, gcode_sha256, filename, total_layers, nominal_spacing_mm),
    )


def get_file(conn: sqlite3.Connection, file_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM files WHERE file_id = ?", (file_id,)
    ).fetchone()


def file_id_exists(conn: sqlite3.Connection, file_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM files WHERE file_id = ?", (file_id,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Layer operations
# ---------------------------------------------------------------------------

def insert_layer(
    conn: sqlite3.Connection,
    file_id: int,
    layer_idx: int,
    z_height_mm: float,
    line_count: int,
    encoded: bool,
    payload_bits: Optional[int] = None,
    correlated_payload: Optional[int] = None,
    cumulative_e_mm: Optional[float] = None,
    time_estimate_s: Optional[int] = None,
    skip_reason: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO layers
            (file_id, layer_idx, z_height_mm, line_count, encoded,
             payload_bits, correlated_payload, cumulative_e_mm,
             time_estimate_s, skip_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id, layer_idx, z_height_mm, line_count,
            1 if encoded else 0,
            payload_bits, correlated_payload,
            cumulative_e_mm, time_estimate_s, skip_reason,
        ),
    )


def lookup_by_payload(
    conn: sqlite3.Connection,
    correlated_payload: int,
) -> Optional[sqlite3.Row]:
    """Find a layer by its correlated (physically-written) payload."""
    return conn.execute(
        """
        SELECT l.*, f.filename, f.total_layers, f.nominal_spacing_mm
        FROM layers l
        JOIN files f ON l.file_id = f.file_id
        WHERE l.correlated_payload = ?
        """,
        (correlated_payload,),
    ).fetchone()


def lookup_by_raw_payload(
    conn: sqlite3.Connection,
    payload_bits: int,
) -> Optional[sqlite3.Row]:
    """Find a layer by its raw (pre-anti-correlation) payload."""
    return conn.execute(
        """
        SELECT l.*, f.filename, f.total_layers, f.nominal_spacing_mm
        FROM layers l
        JOIN files f ON l.file_id = f.file_id
        WHERE l.payload_bits = ?
        """,
        (payload_bits,),
    ).fetchone()


def get_layer(
    conn: sqlite3.Connection,
    file_id: int,
    layer_idx: int,
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM layers WHERE file_id = ? AND layer_idx = ?",
        (file_id, layer_idx),
    ).fetchone()


def get_all_layers(
    conn: sqlite3.Connection,
    file_id: int,
) -> list:
    return conn.execute(
        "SELECT * FROM layers WHERE file_id = ? ORDER BY layer_idx",
        (file_id,),
    ).fetchall()


def update_file_totals(
    conn: sqlite3.Connection,
    file_id: int,
    total_layers: int,
) -> None:
    conn.execute(
        "UPDATE files SET total_layers = ? WHERE file_id = ?",
        (total_layers, file_id),
    )
