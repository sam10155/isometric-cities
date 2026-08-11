"""API budget guard tests (temp DB — never touches the real budget)."""

import pytest

from isomap.apibudget import ApiBudget, BudgetExceeded


def test_spend_counts(tmp_path):
    with ApiBudget(tmp_path / "b.sqlite", cap=10) as b:
        assert b.status().used == 0
        st = b.spend(3)
        assert st.used == 3
        st = b.spend(2)
        assert st.used == 5
        assert st.remaining == 5


def test_cap_enforced_before_spending(tmp_path):
    with ApiBudget(tmp_path / "b.sqlite", cap=10) as b:
        b.spend(9)
        with pytest.raises(BudgetExceeded):
            b.spend(2)  # would breach: refused entirely
        assert b.status().used == 9  # nothing was recorded


def test_apis_tracked_separately(tmp_path):
    with ApiBudget(tmp_path / "b.sqlite", cap=10) as b:
        b.spend(4, api="map_tiles")
        b.spend(2, api="geocoding")
        assert b.status("map_tiles").used == 4
        assert b.status("geocoding").used == 2


def test_free_tier_cost_estimate(tmp_path):
    with ApiBudget(tmp_path / "b.sqlite", cap=5000) as b:
        st = b.spend(1500)
        assert st.est_cost_cad == pytest.approx(500 * 8.4495 / 1000)
