import copy
from pathlib import Path

import pytest

from grc.cli import main
from grc.engine import load, rating, validate

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "maplewood"


@pytest.fixture
def a():
    return load(EXAMPLE).score()


@pytest.mark.parametrize("score,expected", [(25, "Critical"), (15, "Critical"), (14.9, "High"), (10, "High"),
                                            (9.9, "Medium"), (5, "Medium"), (4.9, "Low"), (1, "Low")])
def test_rating_thresholds(score, expected):
    assert rating(score) == expected


def test_residual_never_exceeds_inherent_and_stays_in_range(a):
    for r in a.register:
        assert 1 <= r["residual_score"] <= r["inherent_score"] <= 25


def test_register_is_sorted_by_residual_risk(a):
    scores = [r["residual_score"] for r in a.register]
    assert scores == sorted(scores, reverse=True)


def test_fully_implemented_controls_reduce_likelihood_by_60_percent(a):
    perfect = a.with_controls_implemented(list(a.controls))
    r09 = next(r for r in perfect.register if r["id"] == "R09")  # only preventive controls
    assert r09["residual_likelihood"] == pytest.approx(max(1.0, 3 * 0.4), abs=0.05)


def test_roadmap_is_ranked_by_reduction_per_effort_and_skips_implemented(a):
    rm = a.roadmap()
    assert [x["priority"] for x in rm] == sorted([x["priority"] for x in rm], reverse=True)
    assert all(a.controls[x["control"]]["status"] != "implemented" for x in rm)


def test_implementing_roadmap_reduces_total_risk(a):
    top = [x["control"] for x in a.roadmap()[:5]]
    after = a.with_controls_implemented(top)
    assert after.total_residual() < a.total_residual()
    assert a.controls[top[0]]["status"] != "implemented"  # what-if does not mutate the original


def test_validation_catches_bad_input(a):
    controls = copy.deepcopy(a.controls)
    controls["XX-1"] = {"id": "XX-1", "function": "Protect", "status": "done", "effort": "XL"}
    scenarios = copy.deepcopy(a.scenarios)
    scenarios[0]["controls"].append("PR.ZZ-99")
    scenarios[0]["assets"].append("A99")
    with pytest.raises(ValueError) as err:
        validate(a.assets, controls, scenarios)
    msg = str(err.value)
    assert "NIST CSF 2.0" in msg and "unknown control PR.ZZ-99" in msg and "unknown asset A99" in msg and "effort" in msg


def test_cli_builds_all_deliverables_and_gate(tmp_path):
    assert main(["assess", str(EXAMPLE), "--out", str(tmp_path)]) == 0
    for name in ["risk_register.csv", "risk_register.xlsx", "executive_report.html", "heatmaps.png", "csf_maturity.png"]:
        assert (tmp_path / name).stat().st_size > 0
    assert main(["assess", str(EXAMPLE), "--out", str(tmp_path), "--fail-above", "12"]) == 1
