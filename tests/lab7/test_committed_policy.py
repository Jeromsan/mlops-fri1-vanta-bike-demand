"""The committed gate policy itself: contract, thresholds and settings bounds."""

from pathlib import Path

import pytest

from bike_demand.gate import check_settings, load_policy

pytestmark = pytest.mark.lab7
POLICY = Path(__file__).parents[2] / "configs/gate-policy.yaml"


def test_committed_policy_loads_and_keeps_the_contract():
    policy = load_policy(POLICY)
    assert policy["evaluation"]["expected_rows"] == {
        "train": 8645,
        "validation": 4358,
        "test": 4376,
    }
    assert policy["candidate_settings"]["fixed"] == {"random_state": 42, "n_jobs": 1}
    assert set(policy["rationale"]) >= {"quality", "operation", "integrity"}


def test_candidate_settings_inside_and_outside_bounds():
    policy = load_policy(POLICY)
    good = {
        "n_estimators": 50,
        "max_depth": 10,
        "min_samples_leaf": 1,
        "random_state": 42,
        "n_jobs": 1,
    }
    assert check_settings(good, policy) == []
    assert check_settings({**good, "random_state": 7}, policy) == [
        "random_state must stay 42"
    ]
    assert check_settings({**good, "criterion": "poisson"}, policy) == [
        "settings not allowed by policy: ['criterion']"
    ]
    assert "n_estimators must be an integer" in check_settings(
        {**good, "n_estimators": 50.0}, policy
    )
    assert check_settings({k: v for k, v in good.items() if k != "max_depth"}, policy)
