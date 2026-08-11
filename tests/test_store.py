"""Quadrant store tests (temp DB)."""

from isomap.store import QuadrantStore
from isomap.tilelib import QState


def test_round_trip(tmp_path):
    with QuadrantStore(tmp_path / "q.sqlite") as st:
        assert st.get_state((5, 5)) is QState.EMPTY
        st.set_state((5, 5), QState.PENDING, batch_id="b1")
        assert st.get_state((5, 5)) is QState.PENDING
        st.set_state((5, 5), QState.GENERATED, water_fraction=0.25)
        assert st.get_state((5, 5)) is QState.GENERATED


def test_load_grid_state(tmp_path):
    with QuadrantStore(tmp_path / "q.sqlite") as st:
        st.set_state((0, 0), QState.GENERATED)
        st.set_state((1, 0), QState.PENDING)
        st.set_state((2, 0), QState.GENERATED)
        st.set_state((2, 0), QState.EMPTY)  # explicit empty row still counts as empty
        gs = st.load_grid_state()
    assert gs.get((0, 0)) is QState.GENERATED
    assert gs.get((1, 0)) is QState.PENDING
    assert gs.get((2, 0)) is QState.EMPTY
    assert gs.get((9, 9)) is QState.EMPTY


def test_counts_and_flags(tmp_path):
    with QuadrantStore(tmp_path / "q.sqlite") as st:
        st.set_state((0, 0), QState.GENERATED)
        st.set_state((1, 0), QState.GENERATED)
        st.set_flag((0, 0), True, "bad water color")
        counts = st.counts()
    assert counts["generated"] == 2
