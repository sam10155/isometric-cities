"""Tiling domain logic: quadrant states, seam rules, generation windows, planning.

This module is the single source of truth for seam rules (NYC lesson #13: agents
re-implement logic they can't see — everything tiling-related lives here).

## Domain model

- A *quadrant* is the atomic 512x512px unit, addressed by integer (qx, qy)
  (see gridlib for coordinate conventions).
- A *window* is a 2x2 block of quadrants — one model call renders one window
  (1024x1024px). Quadrants inside the window that are already GENERATED are
  passed to the model as anchor context (their pixels are kept); EMPTY quadrants
  are the *write set* — the model fills them (infill).

## The seam rule

A seam appears wherever newly generated pixels end up adjacent to generated
pixels the model could not see. Therefore a window is valid iff:

  R1: its write set is non-empty (there is something to generate),
  R2: no quadrant inside the window is PENDING (in-flight elsewhere),
  R3: every EDGE (4-)neighbor of every write-set quadrant that lies OUTSIDE the
      window is EMPTY. (PENDING counts as non-empty: concurrent generations
      can't see each other.)

Why 4-neighbors, not 8: a seam is a visible discontinuity along a shared EDGE.
Corner-only contact meets at a single point and must be allowed — with an
8-neighbor rule, extending any region taller than 2 rows is impossible (every
new row's writes diagonally touch the row above outside the window), which
would make the whole scheme unusable. Diagonal color drift is handled by the
post-generation color-normalization stage, not the seam rule.

## Consequences (verified by the test suite — see the visual artifacts)

- A fresh map starts with an all-empty "anchor" window (writes 4 quadrants).
- Growth is a monotone frontier: extending east along the first row pair writes
  2 quadrants/call; each additional row writes 2 per call.
- An empty quadrant flanked by generated content on opposite sides (a 1-wide
  gap) can NEVER be validly generated: the window can't overlap anchors on
  both sides. The planner must never create such gaps; independently-anchored
  regions cannot be seamlessly merged across a 1-wide gap. This is intrinsic
  to the 2x2 scheme, not a planner bug.

## Planner

plan_rect() produces a sequential list of windows that generates every quadrant
in a target rect from any starting state, using a row-major first-valid sweep.
It simulates execution as it plans, so an emitted plan is correct by
construction; if the pre-existing state makes some target quadrants unfillable
(see above) it raises Unfillable listing them. Throughput optimization and
concurrency batching are future work — correctness first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

WINDOW_SIZE = 2  # window edge, in quadrants; one model call = WINDOW_SIZE^2 quadrants


class QState(Enum):
    EMPTY = "empty"
    PENDING = "pending"
    GENERATED = "generated"


Coord = tuple[int, int]


@dataclass
class GridState:
    """Sparse quadrant state map. Anything absent is EMPTY."""

    _states: dict[Coord, QState] = field(default_factory=dict)

    def get(self, q: Coord) -> QState:
        return self._states.get(q, QState.EMPTY)

    def set(self, q: Coord, state: QState) -> None:
        if state is QState.EMPTY:
            self._states.pop(q, None)
        else:
            self._states[q] = state

    def quadrants(self, state: QState) -> set[Coord]:
        return {q for q, s in self._states.items() if s is state}

    def copy(self) -> "GridState":
        return GridState(dict(self._states))


@dataclass(frozen=True)
class Window:
    """A WINDOW_SIZE x WINDOW_SIZE generation window; (qx, qy) is its top-left."""

    qx: int
    qy: int

    def quadrants(self) -> list[Coord]:
        return [
            (self.qx + i, self.qy + j)
            for j in range(WINDOW_SIZE)
            for i in range(WINDOW_SIZE)
        ]

    def contains(self, q: Coord) -> bool:
        return (
            self.qx <= q[0] < self.qx + WINDOW_SIZE
            and self.qy <= q[1] < self.qy + WINDOW_SIZE
        )


def neighbors4(q: Coord) -> list[Coord]:
    x, y = q
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def write_set(state: GridState, w: Window) -> list[Coord]:
    """Quadrants this window would newly generate."""
    return [q for q in w.quadrants() if state.get(q) is QState.EMPTY]


@dataclass(frozen=True)
class Violation:
    rule: str
    quadrant: Coord | None
    detail: str


def validate_window(state: GridState, w: Window) -> list[Violation]:
    """Return all seam-rule violations for generating window w against state.

    Empty list => the window is safe to generate.
    """
    violations: list[Violation] = []
    writes = write_set(state, w)

    if not writes:  # R1
        violations.append(Violation("R1", None, "window has nothing to generate"))

    for q in w.quadrants():  # R2
        if state.get(q) is QState.PENDING:
            violations.append(
                Violation("R2", q, "quadrant is pending in another generation")
            )

    for q in writes:  # R3
        for n in neighbors4(q):
            if not w.contains(n) and state.get(n) is not QState.EMPTY:
                violations.append(
                    Violation(
                        "R3",
                        q,
                        f"write quadrant touches unseen {state.get(n).value} "
                        f"neighbor {n} outside the window",
                    )
                )
    return violations


@dataclass(frozen=True)
class Rect:
    """Inclusive quadrant-index rectangle."""

    min_qx: int
    min_qy: int
    max_qx: int
    max_qy: int

    def quadrants(self) -> list[Coord]:
        return [
            (x, y)
            for y in range(self.min_qy, self.max_qy + 1)
            for x in range(self.min_qx, self.max_qx + 1)
        ]

    @property
    def width(self) -> int:
        return self.max_qx - self.min_qx + 1

    @property
    def height(self) -> int:
        return self.max_qy - self.min_qy + 1

    def contains_window(self, w: Window) -> bool:
        return (
            self.min_qx <= w.qx
            and w.qx + WINDOW_SIZE - 1 <= self.max_qx
            and self.min_qy <= w.qy
            and w.qy + WINDOW_SIZE - 1 <= self.max_qy
        )


class Unfillable(Exception):
    def __init__(self, remaining: set[Coord]):
        self.remaining = remaining
        super().__init__(
            f"{len(remaining)} target quadrant(s) cannot be generated without "
            f"seams from the current state: {sorted(remaining)[:10]}"
            + ("..." if len(remaining) > 10 else "")
        )


@dataclass
class Plan:
    """An ordered, correct-by-construction sequence of generation windows."""

    windows: list[Window]
    new_quadrants: int  # total quadrants the plan generates

    @property
    def calls(self) -> int:
        return len(self.windows)


def plan_rect(state: GridState, rect: Rect) -> Plan:
    """Plan windows to generate every EMPTY quadrant in rect, sequentially.

    Windows are constrained to lie inside rect (a rect thinner than
    WINDOW_SIZE in either dimension is unfillable). The plan simulates its own
    execution, so every emitted window is valid at its point in the sequence.
    Raises Unfillable if target quadrants remain that no in-rect window can
    reach without creating a seam.
    """
    sim = state.copy()
    target = {q for q in rect.quadrants() if sim.get(q) is QState.EMPTY}
    windows: list[Window] = []
    total_writes = 0

    while target:
        placed = False
        # Row-major first-valid sweep: naturally produces anchor + monotone
        # frontier growth and never encloses unfillable gaps in an empty rect.
        for wy in range(rect.min_qy, rect.max_qy - WINDOW_SIZE + 2):
            for wx in range(rect.min_qx, rect.max_qx - WINDOW_SIZE + 2):
                w = Window(wx, wy)
                writes = write_set(sim, w)
                if not any(q in target for q in writes):
                    continue
                if validate_window(sim, w):
                    continue
                windows.append(w)
                for q in writes:
                    sim.set(q, QState.GENERATED)
                    target.discard(q)
                total_writes += len(writes)
                placed = True
                break
            if placed:
                break
        if not placed:
            raise Unfillable(target)

    return Plan(windows=windows, new_quadrants=total_writes)
