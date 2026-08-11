"""CLI smoke tests."""

from isomap.cli import main


def test_info(capsys):
    assert main(["info", "toronto"]) == 0
    out = capsys.readouterr().out
    assert "EPSG:2952" in out
    assert "seed point quadrant" in out


def test_locate(capsys):
    assert main(["locate", "toronto", "--", "-79.3871", "43.6426"]) == 0
    assert "quadrant: (" in capsys.readouterr().out


def test_plan_pilot_dry_run(capsys):
    assert main(["plan", "toronto", "--pilot", "--show", "3"]) == 0
    out = capsys.readouterr().out
    assert "model calls" in out
