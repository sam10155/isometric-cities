"""Seam-rule and planner tests. Each test emits a PNG artifact to debug/tests/
(see debug/tests/index.html after a run) showing the scenario and outcome.
Blue window outline = valid, red = rejected."""

from isomap.testviz import render_plan, render_scenario
from isomap.tilelib import (
    GridState,
    Plan,
    QState,
    Rect,
    Unfillable,
    Window,
    plan_rect,
    validate_window,
    write_set,
)

import pytest


def gen(state: GridState, coords) -> None:
    for q in coords:
        state.set(q, QState.GENERATED)


# --- validate_window: the seam rules ---


def test_anchor_window_on_empty_grid_is_valid():
    s = GridState()
    w = Window(0, 0)
    v = validate_window(s, w)
    render_scenario("01_anchor_valid", s, windows_ok=[w],
                    caption="fresh anchor on empty grid: valid, writes 4")
    assert v == []
    assert len(write_set(s, w)) == 4


def test_fully_generated_window_rejected_r1():
    s = GridState()
    gen(s, Window(0, 0).quadrants())
    w = Window(0, 0)
    v = validate_window(s, w)
    render_scenario("02_nothing_to_write_r1", s, windows_bad=[w],
                    caption="window fully generated: R1, nothing to write")
    assert any(x.rule == "R1" for x in v)


def test_pending_inside_window_rejected_r2():
    s = GridState()
    s.set((1, 0), QState.PENDING)
    w = Window(0, 0)
    v = validate_window(s, w)
    render_scenario("03_pending_inside_r2", s, windows_bad=[w],
                    caption="pending quadrant inside window: R2")
    assert any(x.rule == "R2" for x in v)


def test_edge_adjacent_overlap_valid():
    """Extending east from an anchor: window overlaps the generated column,
    which anchors the two new quadrants — no seam."""
    s = GridState()
    gen(s, Window(0, 0).quadrants())
    w = Window(1, 0)
    v = validate_window(s, w)
    render_scenario("04_overlap_extend_valid", s, windows_ok=[w],
                    caption="eastward extension overlapping anchor column: valid")
    assert v == []
    assert sorted(write_set(s, w)) == [(2, 0), (2, 1)]


def test_touching_without_overlap_rejected_r3():
    """Window placed flush against generated content without overlapping it:
    writes touch unseen generated pixels -> seam."""
    s = GridState()
    gen(s, Window(0, 0).quadrants())
    w = Window(2, 0)
    v = validate_window(s, w)
    render_scenario("05_flush_no_overlap_r3", s, windows_bad=[w],
                    caption="flush placement, no overlap: R3 seam")
    assert any(x.rule == "R3" for x in v)


def test_diagonal_contact_allowed():
    """Corner-only contact is NOT a seam: seams are edge discontinuities.
    (With an 8-neighbor rule, no region taller than 2 rows could ever be
    generated — see tilelib module docstring.)"""
    s = GridState()
    gen(s, Window(0, 0).quadrants())
    w = Window(2, 2)
    v = validate_window(s, w)
    render_scenario("06_diagonal_contact_ok", s, windows_ok=[w],
                    caption="diagonal corner contact only: valid (no shared edge)")
    assert v == []


def test_pending_neighbor_outside_rejected_r3():
    """Concurrent generations can't see each other: a window flush against a
    PENDING block writes pixels along its edge -> R3."""
    s = GridState()
    for q in Window(0, 0).quadrants():
        s.set(q, QState.PENDING)
    w = Window(2, 0)
    v = validate_window(s, w)
    render_scenario("07_pending_neighbor_r3", s, windows_bad=[w],
                    caption="write set edge-touches pending quadrants outside: R3")
    assert any(x.rule == "R3" for x in v)


def test_far_apart_windows_independent():
    s = GridState()
    gen(s, Window(0, 0).quadrants())
    w = Window(3, 0)  # one-quadrant gap: no shared 8-neighbors
    v = validate_window(s, w)
    render_scenario("08_gap_independent_valid", s, windows_ok=[w],
                    caption="1-quadrant gap: independent anchor, valid (merging later is impossible!)")
    assert v == []


def test_single_gap_between_regions_unfillable():
    """The documented intrinsic limitation: a 1-wide empty column between two
    generated regions can never be generated seamlessly."""
    s = GridState()
    gen(s, Window(0, 0).quadrants())
    gen(s, Window(3, 0).quadrants())
    # Any window covering column x=2 must include column 1 or 3 (generated,
    # fine as anchor) — but its write in column 2 touches the OTHER side unseen.
    bad = [Window(1, 0), Window(2, 0)]
    for w in bad:
        assert any(x.rule == "R3" for x in validate_window(s, w))
    render_scenario("09_gap_unfillable", s, windows_bad=bad,
                    caption="1-wide gap between regions: every covering window seams")


# --- plan_rect: the planner ---


def assert_plan_seamless(initial: GridState, plan: Plan, rect: Rect):
    """Re-simulate the plan step by step, asserting every window is valid at
    its point in the sequence and the rect ends fully generated."""
    sim = initial.copy()
    for w in plan.windows:
        assert validate_window(sim, w) == [], f"plan emitted invalid window {w}"
        for q in write_set(sim, w):
            sim.set(q, QState.GENERATED)
    for q in rect.quadrants():
        assert sim.get(q) is QState.GENERATED


def test_plan_2x2_single_call():
    s = GridState()
    rect = Rect(0, 0, 1, 1)
    plan = plan_rect(s, rect)
    render_plan("10_plan_2x2", s, plan, rect)
    assert plan.calls == 1
    assert plan.new_quadrants == 4
    assert_plan_seamless(s, plan, rect)


def test_plan_wide_strip():
    """2-row strip: anchor (4) then eastward extensions (2 each)."""
    s = GridState()
    rect = Rect(0, 0, 7, 1)
    plan = plan_rect(s, rect)
    render_plan("11_plan_strip_8x2", s, plan, rect)
    assert plan.new_quadrants == 16
    assert plan.calls == 7  # 1 anchor + 6 extensions
    assert_plan_seamless(s, plan, rect)


def test_plan_square_region():
    s = GridState()
    rect = Rect(0, 0, 5, 5)
    plan = plan_rect(s, rect)
    render_plan("12_plan_square_6x6", s, plan, rect)
    assert plan.new_quadrants == 36
    assert_plan_seamless(s, plan, rect)


def test_plan_extends_existing_content():
    """Planning a rect that overlaps an already-generated region."""
    s = GridState()
    gen(s, Rect(0, 0, 3, 3).quadrants())
    rect = Rect(0, 0, 7, 3)
    plan = plan_rect(s, rect)
    render_plan("13_plan_extend_east", s, plan, rect)
    assert plan.new_quadrants == 16
    assert_plan_seamless(s, plan, rect)


def test_plan_odd_dimensions():
    """Odd-sized rects force overlapping windows; writes < 4*calls."""
    s = GridState()
    rect = Rect(0, 0, 4, 4)  # 5x5
    plan = plan_rect(s, rect)
    render_plan("14_plan_odd_5x5", s, plan, rect)
    assert plan.new_quadrants == 25
    assert_plan_seamless(s, plan, rect)


def test_plan_1_wide_rect_unfillable():
    s = GridState()
    with pytest.raises(Unfillable):
        plan_rect(s, Rect(0, 0, 0, 5))


def test_plan_trapped_gap_unfillable():
    """Planner must refuse (not seam over) a pre-existing trapped gap."""
    s = GridState()
    gen(s, Rect(0, 0, 1, 1).quadrants())
    gen(s, Rect(3, 0, 4, 1).quadrants())
    with pytest.raises(Unfillable) as exc:
        plan_rect(s, Rect(0, 0, 4, 1))
    assert (2, 0) in exc.value.remaining
    render_scenario("15_plan_trapped_gap", s, target=Rect(0, 0, 4, 1),
                    caption="planner correctly refuses the trapped column")


def test_plan_around_pending():
    """Pending quadrants and their neighborhood are avoided; the rest plans."""
    s = GridState()
    s.set((10, 10), QState.PENDING)
    rect = Rect(0, 0, 5, 5)
    plan = plan_rect(s, rect)
    assert_plan_seamless(s, plan, rect)
