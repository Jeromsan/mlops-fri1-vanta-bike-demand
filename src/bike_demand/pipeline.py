"""Lab 7 entry point: one candidate, one committed policy, one recorded decision.

``run`` trains a candidate from a committed config, evaluates it with the naive
train mean and the accepted incumbent on the same validation rows, applies the
committed gate policy and writes a decision record. It never changes the
accepted state. ``promote`` is a separate, manual command that only accepts an
eligible, committed decision whose candidate bytes, policy and incumbent are
unchanged. See README section "Pipeline and gate".
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import yaml
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

from bike_demand import gate
from bike_demand.api import PredictionInput, infer, load_artifact
from bike_demand.preflight import check_snapshot, sha256
from bike_demand.split import partition_summary, split_data
from bike_demand.store import Store, StoreError, bundle_identity, now
from bike_demand.tracking import Tracking
from bike_demand.train import compare_mean, load_config, select_features
from bike_demand.validate import DOMAINS, FEATURES, load_data

DATA = "data/raw/hour.csv"
DEFAULT_POLICY = "configs/gate-policy.yaml"
DEFAULT_STORE = "artifacts"
DEFAULT_DECISIONS = "reports/decisions"
DEFAULT_PROMOTIONS = "reports/promotions"
# Source paths whose uncommitted changes would make HEAD a false identity.
SOURCE_PATHS = ("src", "configs", "scripts", "pyproject.toml", "uv.lock", "Dockerfile")
PEAK_HOURS = (7, 8, 9, 17, 18, 19)
LIMITATIONS = [
    "One validation window (Jan-Jun 2012) cannot represent every future condition.",
    "Repeated candidate selection on the same window can overfit it; the held "
    "test (Jul-Dec 2012) stays unscored until the final release.",
    "Latency is a warm in-process microbenchmark on the evaluating machine, not a "
    "Cloud Run request latency or SLO.",
    "An eligible outcome is not a deployment: promotion and the Cloud Run identity "
    "check are separate, recorded steps.",
]


# ---- provenance -------------------------------------------------------------


def git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None


def relative(root: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def provenance(root: Path, inputs: list[Path]) -> dict:
    """Which committed revision and inputs does this run actually use?"""
    head = git(root, "rev-parse", "HEAD")
    if head is None or head.returncode != 0:
        return {"commit": None, "reason": "Git revision unavailable"}
    status = git(root, "status", "--porcelain", "--", *SOURCE_PATHS)
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    records = {}
    for path in inputs:
        name = relative(root, path)
        tracked = git(root, "ls-files", "--error-unmatch", "--", name)
        unchanged = git(root, "diff", "--quiet", "HEAD", "--", name)
        last = git(root, "log", "-1", "--format=%H %cI", "--", name)
        commit, _, committed_at = (last.stdout.strip() if last else "").partition(" ")
        records[name] = {
            "tracked": tracked is not None and tracked.returncode == 0,
            "unchanged_since_head": unchanged is not None and unchanged.returncode == 0,
            "last_commit": commit or None,
            "last_commit_time": committed_at or None,
            "sha256": sha256(path) if Path(path).is_file() else None,
        }
    dirty_paths = (
        [line[3:] for line in status.stdout.splitlines()]
        if status and status.returncode == 0
        else None
    )
    lock = root / "uv.lock"
    return {
        "commit": head.stdout.strip(),
        "branch": branch.stdout.strip() if branch else None,
        "source_dirty": None if dirty_paths is None else bool(dirty_paths),
        "dirty_paths": dirty_paths,
        "inputs": records,
        "uv_lock_sha256": sha256(lock) if lock.is_file() else None,
    }


def provenance_problems(prov: dict) -> list[str]:
    if prov.get("commit") is None:
        return [prov.get("reason", "Git revision unavailable")]
    problems = []
    if prov["source_dirty"] is not False:
        problems.append(f"uncommitted source changes: {prov['dirty_paths']}")
    for name, item in prov["inputs"].items():
        if not item["tracked"] or not item["unchanged_since_head"]:
            problems.append(f"{name} must be committed and unchanged")
    return problems


def environment() -> dict:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "scikit_learn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }


# ---- evaluation helpers -----------------------------------------------------


def load_candidate_config(path: Path) -> dict:
    config = yaml.safe_load(Path(path).read_text())
    if not isinstance(config, dict) or set(config) != {
        "data",
        "features",
        "model",
        "candidate",
    }:
        raise ValueError("candidate config: require data, features, model, candidate")
    if config["data"] != DATA:
        raise ValueError("candidate config: use the frozen data/raw/hour.csv")
    if config["features"] != list(FEATURES):
        raise ValueError("candidate config: require the 12 ordered features")
    info = config["candidate"]
    if (
        not isinstance(info, dict)
        or set(info) != {"name", "hypothesis"}
        or not all(isinstance(value, str) and value.strip() for value in info.values())
    ):
        raise ValueError("candidate config: candidate needs a name and a hypothesis")
    return config


def rows_digest(frame: pd.DataFrame) -> str:
    """Identify the exact evaluated rows and labels."""
    payload = frame.loc[:, ["instant", "cnt"]].to_csv(index=False).encode()
    return hashlib.sha256(payload).hexdigest()


def mae(labels: pd.Series, predictions: np.ndarray) -> float:
    return float(mean_absolute_error(labels, predictions))


def payloads(frame: pd.DataFrame, count: int) -> list[PredictionInput]:
    rows = frame.loc[:, list(FEATURES)].head(count).to_dict("records")
    return [
        PredictionInput(
            **{
                name: int(value) if name in DOMAINS else float(value)
                for name, value in row.items()
            }
        )
        for row in rows
    ]


def measure_latency(loaded, requests: list[PredictionInput]) -> dict:
    """Time the serving inference path (frame build + predict) per request."""
    for request in requests[:5]:
        infer(loaded, request)
    timings = []
    for request in requests:
        started = time.perf_counter()
        infer(loaded, request)
        timings.append((time.perf_counter() - started) * 1000)
    return {
        "requests": len(timings),
        "p50_ms": float(np.percentile(timings, 50)),
        "p95_ms": float(np.percentile(timings, 95)),
        "max_ms": float(max(timings)),
    }


def slice_mae(frame: pd.DataFrame, predictions: np.ndarray) -> dict:
    peak = (frame["workingday"] == 1) & frame["hr"].isin(PEAK_HOURS)
    return {
        "working_day_peak_hours": {
            "rows": int(peak.sum()),
            "mae": mae(frame.loc[peak, "cnt"], predictions[peak.to_numpy()]),
        },
        "other_hours": {
            "rows": int((~peak).sum()),
            "mae": mae(frame.loc[~peak, "cnt"], predictions[(~peak).to_numpy()]),
        },
    }


def evaluated_candidates(decisions: Path, policy_sha256: str) -> int:
    if not decisions.exists():
        return 0
    count = 0
    for path in decisions.glob("*.json"):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if (
            record.get("record_type") == "gate_decision"
            and record.get("policy", {}).get("sha256") == policy_sha256
            and record.get("candidate", {}).get("evaluated") is True
        ):
            count += 1
    return count


class Checks:
    def __init__(self):
        self.results: dict[str, dict] = {}

    def add(self, name, status, reason, observed=None, threshold=None):
        self.results[name] = gate.Check(
            name, gate.REQUIRED_CHECKS[name], status, reason, observed, threshold
        ).to_dict()
        return status == "pass"

    def error(self, name, error: Exception):
        return self.add(name, "error", f"{type(error).__name__}: {error}")

    def failed_integrity(self) -> bool:
        return any(
            item["kind"] == "integrity" and item["status"] != "pass"
            for item in self.results.values()
        )

    def ordered(self, reason: str) -> list[dict]:
        for name in gate.REQUIRED_CHECKS:
            if name not in self.results:
                self.add(name, "not_run", reason)
        return [self.results[name] for name in gate.REQUIRED_CHECKS]


# ---- run --------------------------------------------------------------------


def run_candidate(
    root: Path,
    candidate_path: Path,
    policy_path: Path,
    store_root: Path,
    decisions_dir: Path,
) -> tuple[dict, Path]:
    """Train, evaluate and decide one candidate; never touches accepted state."""
    root = Path(root).resolve()
    candidate_path, policy_path = Path(candidate_path), Path(policy_path)
    store = Store(store_root)
    checks = Checks()
    stopped = "an earlier required stage did not pass"
    record = {
        "record_type": "gate_decision",
        "decided_at": None,
        "outcome": None,
        "exit_code": None,
        "reasons": None,
        "checks": None,
        "policy": {"path": relative(root, policy_path), "sha256": None},
        "candidate": {
            "config": relative(root, candidate_path),
            "config_sha256": sha256(candidate_path)
            if candidate_path.is_file()
            else None,
            "evaluated": False,
        },
        "incumbent": None,
        "naive": None,
        "protocol": {
            "metric": "validation MAE, rentals per hour, lower is better",
            "window": "validation 2012-01-01..2012-06-30; held test never scored",
        },
        "provenance": None,
        "environment": environment(),
        "advisory": {},
        "limitations": LIMITATIONS,
    }

    # Stage 1: identity of every input that can change this decision.
    policy = None
    try:
        policy = gate.load_policy(policy_path)
        record["policy"].update(
            version=policy["policy_version"], sha256=sha256(policy_path)
        )
    except gate.PolicyError as error:
        record["policy"]["error"] = str(error)
    prov = provenance(root, [policy_path, candidate_path])
    record["provenance"] = prov
    problems = provenance_problems(prov)
    if policy is None:
        problems.append("policy could not be applied")
    checks.add(
        "source_provenance",
        "fail" if problems else "pass",
        "; ".join(problems) or "clean committed source, policy and candidate config",
        observed={"commit": prov.get("commit"), "branch": prov.get("branch")},
    )

    # Stage 2: data checks (Lecture 7 data gate belongs to integrity here).
    data = root / DATA
    snapshot = None
    try:
        snapshot = check_snapshot(root)
        checks.add(
            "data_snapshot", "pass", "matches data/manifest.json", snapshot["sha256"]
        )
    except (ValueError, OSError, KeyError) as error:
        checks.add("data_snapshot", "fail", str(error))
    partitions = None
    try:
        partitions = split_data(load_data(data))
        checks.add("data_contract", "pass", "domains, dates and chronological split")
    except (ValueError, OSError) as error:
        checks.add("data_contract", "fail", str(error))
    if partitions is not None and policy is not None:
        summary = partition_summary(partitions)
        observed = {name: item["rows"] for name, item in summary.items()}
        expected = policy["evaluation"]["expected_rows"]
        checks.add(
            "partition_rows",
            "pass" if observed == expected else "fail",
            "rows per partition match the policy"
            if observed == expected
            else "rows per partition differ from the policy",
            observed,
            expected,
        )
        record["protocol"]["partitions"] = summary

    # Stage 3: the candidate config and the evaluation budget.
    config = None
    if policy is not None:
        try:
            config = load_candidate_config(candidate_path)
            issues = gate.check_settings(config["model"], policy)
            checks.add(
                "candidate_settings",
                "fail" if issues else "pass",
                "; ".join(issues) or "settings inside the policy bounds",
                config["model"],
                policy["candidate_settings"],
            )
            record["candidate"].update(
                name=config["candidate"]["name"],
                hypothesis=config["candidate"]["hypothesis"],
                settings=config["model"],
            )
        except (ValueError, OSError, yaml.YAMLError) as error:
            checks.add("candidate_settings", "fail", str(error))
        used = evaluated_candidates(decisions_dir, record["policy"]["sha256"])
        limit = policy["budget"]["max_evaluated_candidates"]
        checks.add(
            "budget",
            "pass" if used < limit else "fail",
            f"{used} candidate(s) already evaluated under this policy",
            used,
            limit,
        )
    if checks.failed_integrity() or config is None or partitions is None:
        return finish(record, checks, stopped, decisions_dir, root, None)

    # Stage 4: fit on 2011 only and write to a separate candidate directory.
    train, validation = partitions["train"], partitions["validation"]
    version = f"rf-{uuid.uuid4().hex[:12]}"
    staging = store.candidate_staging(version)
    model = RandomForestRegressor(**config["model"])
    model.fit(select_features(train, config["features"]), train["cnt"])
    joblib.dump(model, staging / "model.joblib")
    written_sha256 = sha256(staging / "model.joblib")
    metadata = {
        "model_version": version,
        "stage": "candidate",
        "created_at": now(),
        "features": list(FEATURES),
        "data_sha256": snapshot["sha256"],
        "training_commit": prov["commit"],
        "working_tree_dirty": prov["source_dirty"],
        "partitions": record["protocol"]["partitions"],
        "config": config,
        "candidate_config_sha256": record["candidate"]["config_sha256"],
        "policy_version": policy["policy_version"],
        "effective_model_settings": model.get_params(),
        "model_sha256": written_sha256,
    }
    (staging / "model-metadata.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n"
    )
    candidate_dir = store.complete_candidate(staging, version)
    del model  # From here on, only the written bytes are evaluated.
    record["candidate"].update(
        model_version=version,
        directory=relative(root, candidate_dir),
        sha256_at_write=written_sha256,
    )

    # Stage 5: integrity of the exact bytes and of the incumbent.
    loaded = None
    try:
        identity = bundle_identity(candidate_dir)
        same = identity["model_sha256"] == written_sha256
        record["candidate"].update(identity=identity)
        checks.add(
            "candidate_bytes",
            "pass" if same else "fail",
            "evaluated bytes are the bytes written by this run"
            if same
            else "candidate bytes changed after writing",
            identity["model_sha256"],
            written_sha256,
        )
        loaded = load_artifact(candidate_dir)
        checks.add(
            "serving_load",
            "pass",
            "loads through the API loader: checksum, feature order, probe",
        )
    except StoreError as error:
        checks.add("candidate_bytes", "fail", str(error))
    except Exception as error:  # the serving loader's own failure is the evidence
        checks.add(
            "serving_load", "fail", f"API loader refused: {type(error).__name__}"
        )

    incumbent = None
    try:
        pointer, incumbent_dir = store.resolve_current()
        incumbent = load_artifact(incumbent_dir)
        incumbent_meta = json.loads((incumbent_dir / "model-metadata.json").read_text())
        record["incumbent"] = {
            "identity": {
                "model_version": pointer["model_version"],
                "model_sha256": pointer["model_sha256"],
            },
            "directory": relative(root, incumbent_dir),
            "training_commit": incumbent_meta.get("training_commit"),
            "training_working_tree_dirty": incumbent_meta.get("working_tree_dirty"),
        }
        checks.add(
            "incumbent_bytes",
            "pass",
            "CURRENT bundle verified and loaded",
            pointer["model_version"],
        )
        comparable = incumbent_meta.get("data_sha256") == snapshot[
            "sha256"
        ] and incumbent_meta.get("features") == list(FEATURES)
        checks.add(
            "comparability",
            "pass" if comparable else "fail",
            "same snapshot and feature contract; scored on the same rows now"
            if comparable
            else "incumbent was trained on another snapshot or feature contract",
            {"data_sha256": incumbent_meta.get("data_sha256")},
            {"data_sha256": snapshot["sha256"]},
        )
    except (StoreError, OSError, ValueError, KeyError) as error:
        checks.add("incumbent_bytes", "fail", f"no verified incumbent: {error}")
    except Exception as error:
        checks.add(
            "incumbent_bytes", "fail", f"incumbent unusable: {type(error).__name__}"
        )

    if loaded is None or incumbent is None or checks.failed_integrity():
        return finish(record, checks, stopped, decisions_dir, root, None)

    # Stage 6: quality on the same rows, then operation on the serving path.
    features = select_features(validation, list(FEATURES))
    labels = validation["cnt"]
    train_mean, naive_mae = compare_mean(train["cnt"], labels)
    candidate_predictions = np.asarray(loaded.model.predict(features), dtype=float)
    incumbent_predictions = np.asarray(incumbent.model.predict(features), dtype=float)
    candidate_mae = mae(labels, candidate_predictions)
    incumbent_mae = mae(labels, incumbent_predictions)
    record["candidate"]["evaluated"] = True
    record["candidate"]["validation_mae"] = candidate_mae
    record["incumbent"]["validation_mae"] = incumbent_mae
    record["naive"] = {"train_mean": train_mean, "validation_mae": naive_mae}
    record["protocol"].update(
        validation_rows=len(validation),
        validation_rows_sha256=rows_digest(validation),
        same_rows_for_all_predictors=True,
    )
    numbers = [candidate_mae, incumbent_mae, naive_mae]
    finite = (
        all(gate.finite_number(value) for value in numbers)
        and np.isfinite(candidate_predictions).all()
        and np.isfinite(incumbent_predictions).all()
        and len(validation) == policy["evaluation"]["expected_rows"]["validation"]
    )
    checks.add(
        "finite_metrics",
        "pass" if finite else "fail",
        "finite predictions and MAEs on the expected rows"
        if finite
        else "non-finite value or unexpected row count",
        {"rows": len(validation)},
    )
    if not finite:
        return finish(record, checks, stopped, decisions_dir, root, None)

    quality = policy["quality"]
    gain_naive = naive_mae - candidate_mae
    checks.add(
        "beats_naive",
        "pass" if gain_naive >= quality["min_gain_vs_naive"] else "fail",
        f"candidate is {gain_naive:.3f} rentals/h better than the train mean",
        round(gain_naive, 6),
        quality["min_gain_vs_naive"],
    )
    gain_incumbent = incumbent_mae - candidate_mae
    checks.add(
        "beats_incumbent",
        "pass" if gain_incumbent >= quality["min_gain_vs_incumbent"] else "fail",
        f"candidate is {gain_incumbent:.3f} rentals/h better than the incumbent",
        round(gain_incumbent, 6),
        quality["min_gain_vs_incumbent"],
    )
    operation = policy["operation"]
    size = record["candidate"]["identity"]["model_bytes"]
    checks.add(
        "model_size",
        "pass" if size <= operation["max_model_bytes"] else "fail",
        f"model file is {size} bytes",
        size,
        operation["max_model_bytes"],
    )
    try:
        requests = payloads(validation, operation["latency_requests"])
        latency = measure_latency(loaded, requests)
        incumbent_latency = measure_latency(incumbent, requests)
        record["candidate"]["latency"] = latency
        record["incumbent"]["latency"] = incumbent_latency
        checks.add(
            "predict_latency",
            "pass" if latency["p95_ms"] <= operation["max_p95_predict_ms"] else "fail",
            f"p95 {latency['p95_ms']:.2f} ms over {latency['requests']} requests",
            round(latency["p95_ms"], 3),
            operation["max_p95_predict_ms"],
        )
    except Exception as error:
        checks.error("predict_latency", error)
    record["advisory"] = {
        "note": "Recorded for review; not part of the gate.",
        "candidate_slices": slice_mae(validation, candidate_predictions),
        "incumbent_slices": slice_mae(validation, incumbent_predictions),
    }

    # Stage 7: a retrievable tracking record of how the candidate was produced.
    run_id = None
    try:
        tracking = Tracking(root)
        context = {
            "training_commit": prov["commit"],
            "data_sha256": snapshot["sha256"],
            "working_tree_dirty": prov["source_dirty"],
            "features": list(FEATURES),
            "partitions": record["protocol"]["partitions"],
        }
        run_id = tracking.start_run("candidate", context, config["model"])
        tracking.client.set_tag(run_id, "stage", "candidate")
        tracking.client.set_tag(run_id, "model_version", version)
        tracking.client.set_tag(run_id, "policy_version", policy["policy_version"])
        tracking.finish(
            run_id,
            candidate_mae,
            [candidate_dir / "model.joblib", candidate_dir / "model-metadata.json"],
        )
        finished = tracking.read_run(run_id).info.status == "FINISHED"
        checks.add(
            "tracking_record",
            "pass" if finished else "fail",
            "MLflow run finished with the candidate bytes",
            run_id,
        )
        record["candidate"]["mlflow_run_id"] = run_id
    except Exception as error:
        checks.error("tracking_record", error)
    return finish(record, checks, stopped, decisions_dir, root, run_id)


def finish(record, checks, stopped, decisions_dir, root, run_id) -> tuple[dict, Path]:
    record["checks"] = checks.ordered(stopped)
    outcome, reasons = gate.decide(record["checks"])
    record.update(
        decided_at=now(),
        outcome=outcome,
        exit_code=gate.EXIT_CODES[outcome],
        reasons=reasons,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = record["candidate"].get("model_version") or "no-candidate"
    decisions_dir = Path(decisions_dir)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_dir / f"{stamp}-{name}.json"
    path.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")
    if run_id is not None:
        try:
            tracking = Tracking(root)
            tracking.client.set_tag(run_id, "gate_outcome", outcome)
            tracking.client.set_tag(run_id, "decision_record", relative(root, path))
        except Exception:
            pass  # the committed decision record remains the authority
    return record, path


# ---- promotion and recovery -------------------------------------------------


def write_change(directory: Path, kind: str, change: dict) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}-{kind}-{change['after']['model_version']}.json"
    path.write_text(json.dumps(change, indent=2, allow_nan=False) + "\n")
    return path


def adopt(
    root: Path,
    store_root: Path,
    source: Path,
    expected_version: str,
    expected_sha256: str,
    approved_by: str,
    note: str,
    promotions_dir: Path,
) -> tuple[dict, Path]:
    """Register the already approved model as the first accepted version."""
    store = Store(store_root)
    if store.read_current() is not None:
        raise StoreError("an accepted version already exists; adopt runs only once")
    identity = bundle_identity(Path(source))
    if (identity["model_version"], identity["model_sha256"]) != (
        expected_version,
        expected_sha256,
    ):
        raise StoreError(
            f"source is {identity['model_version']} / {identity['model_sha256']}, "
            "not the approved record given on the command line"
        )
    acceptance = {
        "action": "adopt",
        "accepted_at": now(),
        "approved_by": approved_by,
        "note": note,
        "source_commit": provenance(Path(root), [])["commit"],
    }
    pointer = store.accept(
        Path(source),
        acceptance,
        expected_current=None,
        change={"action": "adopt", "approved_by": approved_by, "note": note},
    )
    change = {
        "record_type": "pointer_change",
        "action": "adopt",
        "before": None,
        "after": pointer,
        "note": note,
    }
    return pointer, write_change(promotions_dir, "adopt", change)


def promote(
    root: Path,
    decision_path: Path,
    policy_path: Path,
    store_root: Path,
    approved_by: str,
    promotions_dir: Path,
    branch: str = "main",
) -> tuple[dict, Path]:
    """Manual promotion of an eligible, committed decision; refuses otherwise."""
    root = Path(root).resolve()
    record = json.loads(Path(decision_path).read_text())
    problems = gate.verify_record(record)
    if problems:
        raise StoreError(f"decision record is inconsistent: {problems}")
    if record["outcome"] != "eligible":
        raise StoreError(f"decision outcome is {record['outcome']}, not eligible")
    if sha256(Path(policy_path)) != record["policy"]["sha256"]:
        raise StoreError("policy changed since this decision; re-evaluate")
    prov = provenance(root, [Path(policy_path), Path(decision_path)])
    issues = provenance_problems(prov)
    if prov.get("branch") != branch:
        issues.append(f"promote from reviewed {branch}, not {prov.get('branch')}")
    if issues:
        raise StoreError("; ".join(issues))
    store = Store(store_root)
    version = record["candidate"]["model_version"]
    identity = bundle_identity(store.candidate_dir(version))
    if identity["model_sha256"] != record["candidate"]["sha256_at_write"]:
        raise StoreError("candidate bytes differ from the evaluated bytes")
    before = record["incumbent"]["identity"]
    acceptance = {
        "action": "promote",
        "accepted_at": now(),
        "approved_by": approved_by,
        "approval_commit": prov["commit"],
        "decision_record": relative(root, Path(decision_path)),
        "decision_sha256": sha256(Path(decision_path)),
        "policy_version": record["policy"]["version"],
        "policy_sha256": record["policy"]["sha256"],
        "candidate_validation_mae": record["candidate"]["validation_mae"],
        "replaces": before,
    }
    pointer = store.accept(
        store.candidate_dir(version),
        acceptance,
        expected_current=before,
        change={
            "action": "promote",
            "approved_by": approved_by,
            "approval_commit": prov["commit"],
            "decision_record": acceptance["decision_record"],
        },
    )
    change = {
        "record_type": "pointer_change",
        "action": "promote",
        "before": before,
        "after": pointer,
        "decision_record": acceptance["decision_record"],
        "approved_by": approved_by,
    }
    return pointer, write_change(promotions_dir, "promote", change)


def restore(
    store_root: Path,
    version: str,
    approved_by: str,
    reason: str,
    promotions_dir: Path,
) -> tuple[dict, Path]:
    """Point CURRENT back to a retained accepted version, without retraining."""
    store = Store(store_root)
    current = store.read_current()
    acceptance = json.loads(
        (store.version_dir(version) / "acceptance.json").read_text()
    )
    identity = store.verify_version(version, acceptance["model_sha256"])
    before = (
        None
        if current is None
        else {
            "model_version": current["model_version"],
            "model_sha256": current["model_sha256"],
        }
    )
    pointer = store.switch(
        identity,
        expected_current=before,
        change={"action": "restore", "approved_by": approved_by, "reason": reason},
    )
    change = {
        "record_type": "pointer_change",
        "action": "restore",
        "before": before,
        "after": pointer,
        "reason": reason,
    }
    return pointer, write_change(promotions_dir, "restore", change)


def seed_variation(root: Path, config_path: Path, seeds: list[int]) -> dict:
    """Execution variation of the accepted settings: only the seed changes."""
    root = Path(root).resolve()
    config = load_config(Path(config_path))
    snapshot = check_snapshot(root)
    partitions = split_data(load_data(root / DATA))
    train, validation = partitions["train"], partitions["validation"]
    scores = {}
    for seed in seeds:
        model = RandomForestRegressor(**{**config["model"], "random_state": seed})
        model.fit(select_features(train, config["features"]), train["cnt"])
        predictions = model.predict(select_features(validation, config["features"]))
        scores[str(seed)] = mae(validation["cnt"], predictions)
    values = list(scores.values())
    return {
        "record_type": "seed_variation",
        "measured_at": now(),
        "purpose": "Execution variation of the accepted RF settings, used to size "
        "the incumbent margin before any candidate is evaluated.",
        "config": relative(root, Path(config_path)),
        "settings": config["model"],
        "varied": "random_state only",
        "data_sha256": snapshot["sha256"],
        "validation_rows": len(validation),
        "validation_mae": scores,
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
        "mean": float(np.mean(values)),
        "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        "provenance": provenance(root, [Path(config_path)]),
        "environment": environment(),
        "limitation": "Seed spread is execution variation on one window; it is not "
        "uncertainty about future demand.",
    }


def verify_records(directory: Path) -> dict:
    results = {}
    for path in sorted(Path(directory).glob("*.json")):
        try:
            problems = gate.verify_record(json.loads(path.read_text()))
        except ValueError as error:
            problems = [f"invalid JSON: {error}"]
        results[path.as_posix()] = problems
    return results


# ---- command line -----------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", type=Path, default=Path(DEFAULT_STORE))
    parser.add_argument("--decisions", type=Path, default=Path(DEFAULT_DECISIONS))
    parser.add_argument("--promotions", type=Path, default=Path(DEFAULT_PROMOTIONS))
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="train, evaluate and decide one candidate")
    run.add_argument("--candidate", type=Path, required=True)
    run.add_argument("--policy", type=Path, default=Path(DEFAULT_POLICY))

    adopt_cmd = commands.add_parser("adopt", help="register the approved model once")
    adopt_cmd.add_argument("--from", dest="source", type=Path, required=True)
    adopt_cmd.add_argument("--expected-version", required=True)
    adopt_cmd.add_argument("--expected-sha256", required=True)
    adopt_cmd.add_argument("--approved-by", required=True)
    adopt_cmd.add_argument("--note", required=True)

    promote_cmd = commands.add_parser("promote", help="manual reviewed promotion")
    promote_cmd.add_argument("--decision", type=Path, required=True)
    promote_cmd.add_argument("--policy", type=Path, default=Path(DEFAULT_POLICY))
    promote_cmd.add_argument("--approved-by", required=True)
    promote_cmd.add_argument("--branch", default="main")

    restore_cmd = commands.add_parser("restore", help="point back to a kept version")
    restore_cmd.add_argument("--version", required=True)
    restore_cmd.add_argument("--approved-by", required=True)
    restore_cmd.add_argument("--reason", required=True)

    commands.add_parser("status", help="show and verify the accepted state")
    commands.add_parser("verify-records", help="recompute stored decision outcomes")

    seeds = commands.add_parser("seed-variation", help="measure seed-only variation")
    seeds.add_argument("--config", type=Path, default=Path("configs/baseline.yaml"))
    seeds.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    seeds.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    root = Path.cwd()
    try:
        if args.command == "run":
            record, path = run_candidate(
                root, args.candidate, args.policy, args.store, args.decisions
            )
            print(json.dumps(summary(record, path), indent=2))
            return record["exit_code"]
        if args.command == "adopt":
            pointer, path = adopt(
                root,
                args.store,
                args.source,
                args.expected_version,
                args.expected_sha256,
                args.approved_by,
                args.note,
                args.promotions,
            )
        elif args.command == "promote":
            pointer, path = promote(
                root,
                args.decision,
                args.policy,
                args.store,
                args.approved_by,
                args.promotions,
                args.branch,
            )
        elif args.command == "restore":
            pointer, path = restore(
                args.store, args.version, args.approved_by, args.reason, args.promotions
            )
        elif args.command == "status":
            print(json.dumps(Store(args.store).status(), indent=2))
            return 0
        elif args.command == "verify-records":
            results = verify_records(args.decisions)
            print(json.dumps(results, indent=2))
            return 1 if any(results.values()) else 0
        else:
            result = seed_variation(root, args.config, args.seeds)
            text = json.dumps(result, indent=2, allow_nan=False) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text)
            print(text, end="")
            return 0
    except (StoreError, ValueError, OSError, KeyError) as error:
        print(f"{args.command} refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"pointer": pointer, "record": path.as_posix()}, indent=2))
    return 0


def summary(record: dict, path: Path) -> dict:
    return {
        "outcome": record["outcome"],
        "exit_code": record["exit_code"],
        "reasons": record["reasons"],
        "candidate": record["candidate"].get("model_version"),
        "candidate_validation_mae": record["candidate"].get("validation_mae"),
        "incumbent": (record["incumbent"] or {}).get("identity"),
        "incumbent_validation_mae": (record["incumbent"] or {}).get("validation_mae"),
        "naive_validation_mae": (record["naive"] or {}).get("validation_mae"),
        "decision_record": path.as_posix(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
