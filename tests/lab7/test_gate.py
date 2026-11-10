"""Policy validation and outcome rules; no training here."""

import pytest
import yaml
from conftest import policy_for

from bike_demand import gate
from bike_demand.gate import (
    REQUIRED_CHECKS,
    PolicyError,
    decide,
    finite_number,
    load_policy,
    verify_record,
)

pytestmark = pytest.mark.lab7
ROWS = {"train": 8645, "validation": 4358, "test": 4376}


def all_pass() -> list[dict]:
    return [
        gate.Check(name, kind, "pass", "ok").to_dict()
        for name, kind in REQUIRED_CHECKS.items()
    ]


def with_status(name: str, status: str) -> list[dict]:
    return [
        {**check, "status": status, "reason": "observed"}
        if check["name"] == name
        else check
        for check in all_pass()
    ]


def test_all_required_checks_pass_is_eligible():
    assert decide(all_pass()) == (
        "eligible",
        ["all required integrity, quality and operation checks passed"],
    )


@pytest.mark.parametrize("name", ["beats_incumbent", "beats_naive", "model_size"])
def test_measured_quality_or_operation_failure_rejects(name):
    outcome, reasons = decide(with_status(name, "fail"))
    assert outcome == "rejected"
    assert reasons == [f"{name}: observed"]


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("candidate_bytes", "fail"),
        ("source_provenance", "fail"),
        ("incumbent_bytes", "fail"),
        ("beats_incumbent", "not_run"),
        ("predict_latency", "error"),
    ],
)
def test_invalid_or_unavailable_evidence_blocks(name, status):
    outcome, reasons = decide(with_status(name, status))
    assert outcome == "blocked"
    assert reasons[0].startswith(name)


def test_missing_check_blocks_even_when_quality_improves():
    checks = [check for check in all_pass() if check["name"] != "comparability"]
    assert decide(checks) == ("blocked", ["comparability: required check missing"])


def test_duplicate_and_mislabelled_checks_block():
    checks = all_pass()
    assert decide([*checks, checks[0]])[0] == "blocked"
    mislabelled = [
        {**check, "kind": "quality"} if check["name"] == "data_snapshot" else check
        for check in checks
    ]
    assert decide(mislabelled) == (
        "blocked",
        ["data_snapshot: malformed check result"],
    )


def test_blocked_has_priority_over_rejected():
    checks = with_status("beats_incumbent", "fail")
    checks = [
        {**check, "status": "error"} if check["name"] == "tracking_record" else check
        for check in checks
    ]
    assert decide(checks)[0] == "blocked"


@pytest.mark.parametrize(
    "value", [True, False, float("nan"), float("inf"), "1", None, 10**400]
)
def test_finite_number_rejects_non_numbers(value):
    assert finite_number(value) is False


def test_finite_number_accepts_plain_numbers():
    assert finite_number(1) and finite_number(0.5)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("operation", "latency_requests"), 5, "at least 20"),
        (("operation", "max_p95_predict_ms"), True, "positive finite"),
        (("quality", "min_gain_vs_naive"), 0, "positive finite"),
        (("quality", "min_gain_vs_incumbent"), -1, "positive finite"),
        (("evaluation", "window"), "test", "validation window"),
        (("primary_metric", "direction"), "higher", "primary metric"),
        (("candidate_settings", "fixed"), {"random_state": 0}, "stay fixed"),
        (("budget", "max_evaluated_candidates"), 0, "positive finite"),
    ],
)
def test_invalid_policy_cannot_be_applied(tmp_path, path, value, message):
    policy = policy_for(ROWS)
    section, key = path
    policy[section][key] = value
    target = tmp_path / "policy.yaml"
    target.write_text(yaml.safe_dump(policy))
    with pytest.raises(PolicyError, match=message):
        load_policy(target)


def test_policy_with_unknown_section_is_refused(tmp_path):
    policy = policy_for(ROWS)
    policy["override"] = {"skip_checks": True}
    target = tmp_path / "policy.yaml"
    target.write_text(yaml.safe_dump(policy))
    with pytest.raises(PolicyError, match="exactly"):
        load_policy(target)


def test_tampered_record_is_detected():
    record = {key: None for key in gate.RECORD_KEYS}
    checks = with_status("beats_incumbent", "fail")
    record.update(
        record_type="gate_decision",
        checks=checks,
        outcome="rejected",
        exit_code=2,
        reasons=decide(checks)[1],
    )
    assert verify_record(record) == []
    edited = {**record, "outcome": "eligible", "exit_code": 0}
    problems = verify_record(edited)
    assert any("differs from recomputed 'rejected'" in item for item in problems)
