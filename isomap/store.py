"""SQLite quadrant state store.

One database per city (cities/<name>/quadrants.sqlite). The DB is the source of
truth for generation state; tilelib.GridState is the in-memory working copy.
Boring by design: plain sqlite3, no ORM.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .tilelib import Coord, GridState, QState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quadrants (
    qx INTEGER NOT NULL,
    qy INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'empty',
    water_fraction REAL,           -- 0..1, from the water classifier (Phase 4)
    batch_id TEXT,                 -- generation batch that produced it
    flagged INTEGER NOT NULL DEFAULT 0,  -- human QA flag
    note TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (qx, qy)
);

CREATE TABLE IF NOT EXISTS boundary (
    -- city export boundary polygon, edited by the bounds app (Phase 1)
    seq INTEGER PRIMARY KEY,
    lon REAL NOT NULL,
    lat REAL NOT NULL
);
"""


class QuadrantStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "QuadrantStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def set_state(
        self,
        q: Coord,
        state: QState,
        batch_id: str | None = None,
        water_fraction: float | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO quadrants (qx, qy, state, batch_id, water_fraction, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT (qx, qy) DO UPDATE SET
                state = excluded.state,
                batch_id = COALESCE(excluded.batch_id, quadrants.batch_id),
                water_fraction = COALESCE(excluded.water_fraction, quadrants.water_fraction),
                updated_at = excluded.updated_at
            """,
            (q[0], q[1], state.value, batch_id, water_fraction),
        )
        self._conn.commit()

    def get_state(self, q: Coord) -> QState:
        row = self._conn.execute(
            "SELECT state FROM quadrants WHERE qx = ? AND qy = ?", q
        ).fetchone()
        return QState(row[0]) if row else QState.EMPTY

    def set_flag(self, q: Coord, flagged: bool, note: str | None = None) -> None:
        self._conn.execute(
            """
            INSERT INTO quadrants (qx, qy, flagged, note) VALUES (?, ?, ?, ?)
            ON CONFLICT (qx, qy) DO UPDATE SET
                flagged = excluded.flagged,
                note = COALESCE(excluded.note, quadrants.note),
                updated_at = datetime('now')
            """,
            (q[0], q[1], int(flagged), note),
        )
        self._conn.commit()

    def load_grid_state(self) -> GridState:
        gs = GridState()
        for qx, qy, state in self._conn.execute(
            "SELECT qx, qy, state FROM quadrants WHERE state != 'empty'"
        ):
            gs.set((qx, qy), QState(state))
        return gs

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT state, COUNT(*) FROM quadrants GROUP BY state"
        ).fetchall()
        return {state: n for state, n in rows}
