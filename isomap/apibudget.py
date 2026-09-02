"""Google Maps API budget guard — session-first billing model.

Working model (2026-08, matching the Isometric NYC project's cost profile):
3D Tiles billing rides on ROOT TILESET SESSIONS — one root.json request opens
a >=3h session and subsequent tile fetches ride on it (per Google's 3D Tiles
docs). We therefore track TWO counters:

- 'map_tiles_session' (primary, assumed billable): root.json fetches.
  Free tier 1,000/month, then CAD 8.4495/1k. Cap: 100/month — no realistic
  workflow needs more (3h sessions => ~8/day of continuous work), and 100
  sessions is 10% of the free tier.
- 'map_tiles' (diagnostic): every raw HTTP request, with a loose runaway
  backstop of 100k/month. NOT assumed billable, but tracked so we can compare
  against the Cloud Console SKU report and detect if the model is wrong.

VERIFY EARLY: check Billing -> Reports -> SKU 'Photorealistic 3D Tiles'
usage count against these counters after fetch runs. If SKU count tracks raw
requests rather than sessions, revert to request-based caps immediately
(the pilot region would then cost ~CAD 42, full Toronto ~CAD 1,260).

Cache-first remains the companion rule: fetched responses are stored
permanently on disk so nothing is ever requested twice.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import REPO_ROOT

FREE_TIER = 1000
COST_PER_1K_CAD = 8.4495

# per-API monthly caps; sessions are the primary (billable) unit
DEFAULT_CAPS = {
    "map_tiles_session": 100,   # root.json fetches — the assumed-billable unit
    "map_tiles": 200_000,       # raw requests — runaway backstop, not billing
                                # (raised 2026-08-27 w/ user approval; session
                                # billing verified, raw traffic is free)
}
DEFAULT_MONTHLY_CAP = 100_000  # fallback for unknown APIs

BUDGET_DB = REPO_ROOT / "cities" / "api_budget.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    month TEXT NOT NULL,          -- 'YYYY-MM' (UTC)
    api TEXT NOT NULL,            -- e.g. 'map_tiles'
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (month, api)
);
"""


class BudgetExceeded(RuntimeError):
    pass


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@dataclass
class BudgetStatus:
    month: str
    used: int
    cap: int

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    @property
    def est_cost_cad(self) -> float:
        billable = max(0, self.used - FREE_TIER)
        return billable * COST_PER_1K_CAD / 1000

    def __str__(self) -> str:
        return (f"{self.month}: {self.used}/{self.cap} requests used "
                f"({self.remaining} remaining, est. CAD {self.est_cost_cad:.2f})")


class ApiBudget:
    def __init__(
        self,
        db_path: Path | str = BUDGET_DB,
        cap: int | None = None,
        caps: dict[str, int] | None = None,
    ):
        """cap: override applied to every API (tests). caps: per-API overrides
        merged over DEFAULT_CAPS."""
        self._flat_cap = cap
        self.caps = {**DEFAULT_CAPS, **(caps or {})}
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: Tiles3dClient calls spend() from fetch
        # workers, serialized under its own lock (no concurrent access)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def cap_for(self, api: str) -> int:
        if self._flat_cap is not None:
            return self._flat_cap
        return self.caps.get(api, DEFAULT_MONTHLY_CAP)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ApiBudget":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def status(self, api: str = "map_tiles") -> BudgetStatus:
        month = _current_month()
        row = self._conn.execute(
            "SELECT count FROM requests WHERE month = ? AND api = ?", (month, api)
        ).fetchone()
        return BudgetStatus(month=month, used=row[0] if row else 0, cap=self.cap_for(api))

    def spend(self, n: int = 1, api: str = "map_tiles") -> BudgetStatus:
        """Record n requests, raising BEFORE spending if it would breach the cap."""
        st = self.status(api)
        if st.used + n > st.cap:
            raise BudgetExceeded(
                f"refusing {n} '{api}' request(s): {st.used}/{st.cap} already used "
                f"in {st.month}. Raise the cap explicitly if you accept the cost "
                f"(CAD {COST_PER_1K_CAD}/1k past {FREE_TIER})."
            )
        self._conn.execute(
            """
            INSERT INTO requests (month, api, count) VALUES (?, ?, ?)
            ON CONFLICT (month, api) DO UPDATE SET count = count + excluded.count
            """,
            (st.month, api, n),
        )
        self._conn.commit()
        return self.status(api)


def api_key() -> str:
    """Read GOOGLE_MAPS_API_KEY from the environment or the repo .env file."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if key:
        return key
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("GOOGLE_MAPS_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("GOOGLE_MAPS_API_KEY not set (env var or .env file)")


def tile_cache_dir(city_name: str) -> Path:
    """Permanent on-disk cache for fetched tile data — never re-fetch."""
    d = REPO_ROOT / "cities" / city_name / "tile_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d
