"""Gate policy: a committed rule set turned into an explainable decision.

The gate never trains or loads models. It validates the policy file, records one
result per required check and derives the outcome from those results only:

- ``blocked``: evidence is invalid, missing or did not run. Repair, then rerun.
- ``rejected``: all evidence is valid and a measured quality/operation rule failed.
- ``eligible``: every required check passed. Promotion is still a separate,
  manual and reviewed action.
"""

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

OUTCOMES = ("eligible", "rejected", "blocked")
# How CI or a shell observes the outcome. 1 is reserved for crashes/usage errors.
EXIT_CODES = {"eligible": 0, "rejected": 2, "blocked": 3}
STATUSES = ("pass", "fail", "error", "not_run")
KINDS = ("integrity", "quality", "operation")

# Every check below must appear in a decision record. A missing name blocks.
REQUIRED_CHECKS = {
    "source_provenance": "integrity",
    "data_snapshot": "integrity",
    "data_contract": "integrity",
    "partition_rows": "integrity",
    "candidate_settings": "integrity",
    "budget": "integrity",
    "candidate_bytes": "integrity",
    "incumbent_bytes": "integrity",
    "comparability": "integrity",
    "finite_metrics": "integrity",
    "tracking_record": "integrity",
    "beats_naive": "quality",
    "beats_incumbent": "quality",
    "serving_load": "operation",
    "model_size": "operation",
    "predict_latency": "operation",
}

SETTING_TYPES = {
    "n_estimators": int,
    "max_depth": int,
    "min_samples_leaf": int,
}
POLICY_KEYS = {
    "policy_version",
    "rationale",
    "primary_metric",
    "evaluation",
    "quality",
    "operation",
    "candidate_settings",
    "budget",
}


class PolicyError(ValueError):
    """The policy file cannot be applied; no decision can be derived from it."""


def finite_number(value: Any) -> bool:
    """Lecture 7 primitive: reject booleans, non-finite and oversized values."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class Check:
    name: str
    kind: str
    status: str
    reason: str
    observed: Any = None
    threshold: Any = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"check {self.name}: unknown kind {self.kind}")
        if self.status not in STATUSES:
            raise ValueError(f"check {self.name}: unknown status {self.status}")

    def to_dict(self) -> dict:
        return asdict(self)


def _positive(section: dict, key: str, *, allow_zero=False, integer=False) -> None:
    value = section.get(key)
    valid_type = type(value) is int if integer else finite_number(value)
    if not valid_type or value < 0 or (value == 0 and not allow_zero):
        raise PolicyError(f"policy: {key} must be a positive finite number")


def load_policy(path: Path) -> dict:
    try:
        policy = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError) as error:
        raise PolicyError(f"policy: cannot read {path}: {type(error).__name__}")
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise PolicyError(f"policy: require exactly {sorted(POLICY_KEYS)}")
    if not isinstance(policy["policy_version"], str) or not policy["policy_version"]:
        raise PolicyError("policy: policy_version must be a nonempty string")
    metric = policy["primary_metric"]
    if metric != {
        "name": "validation_mae",
        "unit": "rentals per hour",
        "direction": "lower_is_better",
    }:
        raise PolicyError("policy: primary metric must be validation MAE, lower")
    evaluation = policy["evaluation"]
    rows = evaluation.get("expected_rows") if isinstance(evaluation, dict) else None
    if (
        not isinstance(evaluation, dict)
        or evaluation.get("window") != "validation"
        or not isinstance(rows, dict)
        or set(rows) != {"train", "validation", "test"}
        or not all(type(value) is int and value > 0 for value in rows.values())
    ):
        raise PolicyError("policy: evaluation must use the validation window")
    quality = policy["quality"]
    if not isinstance(quality, dict) or set(quality) != {
        "min_gain_vs_naive",
        "min_gain_vs_incumbent",
    }:
        raise PolicyError("policy: quality needs both naive and incumbent margins")
    _positive(quality, "min_gain_vs_naive")
    _positive(quality, "min_gain_vs_incumbent", allow_zero=True)
    operation = policy["operation"]
    if not isinstance(operation, dict) or set(operation) != {
        "max_model_bytes",
        "max_p95_predict_ms",
        "latency_requests",
    }:
        raise PolicyError("policy: operation needs size, latency and sample size")
    _positive(operation, "max_model_bytes", integer=True)
    _positive(operation, "max_p95_predict_ms")
    _positive(operation, "latency_requests", integer=True)
    if operation["latency_requests"] < 20:
        raise PolicyError("policy: latency_requests must be at least 20")
    settings = policy["candidate_settings"]
    if not isinstance(settings, dict) or set(settings) != {"allowed", "fixed"}:
        raise PolicyError("policy: candidate_settings needs allowed and fixed")
    if settings["fixed"] != {"random_state": 42, "n_jobs": 1}:
        raise PolicyError("policy: random_state 42 and n_jobs 1 stay fixed")
    allowed = settings["allowed"]
    if not isinstance(allowed, dict) or not set(allowed) <= set(SETTING_TYPES):
        raise PolicyError(f"policy: allowed settings are {sorted(SETTING_TYPES)}")
    for name, bounds in allowed.items():
        if (
            not isinstance(bounds, dict)
            or set(bounds) - {"min", "max", "allow_none"}
            or not {"min", "max"} <= set(bounds)
            or type(bounds["min"]) is not int
            or type(bounds["max"]) is not int
            or not 1 <= bounds["min"] <= bounds["max"]
            or type(bounds.get("allow_none", False)) is not bool
        ):
            raise PolicyError(f"policy: invalid bounds for {name}")
    budget = policy["budget"]
    if not isinstance(budget, dict) or set(budget) != {"max_evaluated_candidates"}:
        raise PolicyError("policy: budget needs max_evaluated_candidates")
    _positive(budget, "max_evaluated_candidates", integer=True)
    if not isinstance(policy["rationale"], dict):
        raise PolicyError("policy: rationale must explain each rule")
    return policy


def check_settings(settings: Any, policy: dict) -> list[str]:
    """Return every reason a candidate's model settings are outside the policy."""
    if not isinstance(settings, dict):
        return ["model settings must be a mapping"]
    allowed = policy["candidate_settings"]["allowed"]
    fixed = policy["candidate_settings"]["fixed"]
    problems = []
    unknown = set(settings) - set(allowed) - set(fixed)
    if unknown:
        problems.append(f"settings not allowed by policy: {sorted(unknown)}")
    for name, value in fixed.items():
        if settings.get(name) != value or type(settings.get(name)) is not type(value):
            problems.append(f"{name} must stay {value}")
    for name, bounds in allowed.items():
        if name not in settings:
            problems.append(f"{name} must be declared explicitly")
            continue
        value = settings[name]
        if value is None and bounds.get("allow_none", False):
            continue
        if type(value) is not SETTING_TYPES[name]:
            problems.append(f"{name} must be an integer")
        elif not bounds["min"] <= value <= bounds["max"]:
            problems.append(
                f"{name}={value} outside [{bounds['min']}, {bounds['max']}]"
            )
    return problems


def decide(checks: list[dict]) -> tuple[str, list[str]]:
    """Derive the outcome from observed check results, never from a stored flag."""
    by_name: dict[str, dict] = {}
    reasons = []
    for check in checks:
        name = check.get("name")
        if name in by_name:
            reasons.append(f"{name}: recorded twice")
        by_name[name] = check
    for name, kind in REQUIRED_CHECKS.items():
        check = by_name.get(name)
        if check is None:
            reasons.append(f"{name}: required check missing")
        elif check.get("kind") != kind or check.get("status") not in STATUSES:
            reasons.append(f"{name}: malformed check result")
        elif check["status"] in ("error", "not_run"):
            reasons.append(f"{name}: {check['status']} ({check.get('reason')})")
        elif kind == "integrity" and check["status"] != "pass":
            reasons.append(f"{name}: integrity failed ({check.get('reason')})")
    if reasons:
        return "blocked", reasons
    failed = [
        f"{name}: {by_name[name].get('reason')}"
        for name in REQUIRED_CHECKS
        if by_name[name]["status"] == "fail"
    ]
    if failed:
        return "rejected", failed
    return "eligible", ["all required integrity, quality and operation checks passed"]


RECORD_KEYS = {
    "record_type",
    "decided_at",
    "outcome",
    "exit_code",
    "reasons",
    "checks",
    "policy",
    "candidate",
    "incumbent",
    "naive",
    "protocol",
    "provenance",
    "environment",
    "advisory",
    "limitations",
}


def verify_record(record: Any) -> list[str]:
    """Return problems with a stored decision record; empty means consistent."""
    if not isinstance(record, dict):
        return ["record is not a JSON object"]
    problems = []
    missing = RECORD_KEYS - set(record)
    if missing:
        problems.append(f"missing fields: {sorted(missing)}")
        return problems
    if record["record_type"] != "gate_decision":
        problems.append("record_type must be gate_decision")
    if record["outcome"] not in OUTCOMES:
        problems.append("unknown outcome")
    outcome, reasons = decide(record["checks"])
    if outcome != record["outcome"]:
        problems.append(
            f"stored outcome {record['outcome']!r} differs from recomputed {outcome!r}"
        )
    if record["exit_code"] != EXIT_CODES.get(record["outcome"]):
        problems.append("exit_code does not match outcome")
    if record["reasons"] != reasons:
        problems.append("stored reasons differ from recomputed reasons")
    return problems
