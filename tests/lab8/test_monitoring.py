"""Signal definitions and probe workload for the Lab 8 monitoring loop."""

import json
import runpy
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bike_demand.api import create_app
from bike_demand.split import WINDOWS
from bike_demand.validate import FEATURES

pytestmark = pytest.mark.lab8
SCRIPTS = Path(__file__).parents[2] / "scripts"
PROBE = runpy.run_path(str(SCRIPTS / "probe.py"))
SIGNALS = runpy.run_path(str(SCRIPTS / "signals.py"))
DATA = Path(__file__).parents[2] / "data/raw/hour.csv"
# A validation-period row (2012-01-01) and a held-test row (2012-07-01).
VALIDATION_INSTANT, TEST_INSTANT = 8646, 13004
EXPECTED = {"model_version": "baseline-a", "model_sha256": "a" * 64}


def attempt(kind, status=200, **fields):
    row = {
        "period": "p",
        "target": "http://t",
        "kind": kind,
        "status": status,
        "sent_at": f"2026-11-13T09:00:{len(fields):02d}+00:00",
        "duration_ms": 10.0,
    }
    if kind == "valid":
        row["instant"] = VALIDATION_INSTANT
    return {**row, **fields}


def compute(rows, expected=None):
    return SIGNALS["compute"](rows, expected, DATA)


def test_zero_eligible_attempts_is_no_evidence_not_success():
    result = compute([attempt("health")])
    assert result["prediction_success"] == {
        "good": 0,
        "eligible": 0,
        "ratio": None,
        "note": "no evidence",
    }
    assert result["replay_quality"]["mae"] is None


def test_timeouts_count_as_failed_valid_attempts():
    rows = [
        attempt("valid", prediction=10.0, model_version="baseline-a"),
        attempt("valid", status=None, error="TimeoutError"),
        attempt("valid", status=503),
    ]
    result = compute(rows)
    assert result["prediction_success"]["good"] == 1
    assert result["prediction_success"]["eligible"] == 3
    assert result["failures_by_cause"] == {"TimeoutError": 1, "503": 1}
    assert result["latency_success"]["n"] == 1
    assert result["latency_failed"]["n"] == 2


def test_negative_or_unversioned_predictions_are_not_good():
    rows = [
        attempt("valid", prediction=-1.0, model_version="baseline-a"),
        attempt("valid", prediction=5.0, model_version=""),
    ]
    assert compute(rows)["prediction_success"]["good"] == 0


def test_invalid_requests_are_good_only_when_rejected_with_4xx():
    rows = [
        attempt("invalid", status=422),
        attempt("invalid", status=200),
        attempt("invalid", status=503),
        attempt("invalid", status=None, error="URLError"),
    ]
    result = compute(rows)["invalid_rejection"]
    assert (result["good"], result["eligible"]) == (1, 4)


def test_identity_match_uses_the_retained_record_not_the_service():
    rows = [
        attempt("valid", prediction=1.0, model_version="baseline-a"),
        attempt("valid", prediction=1.0, model_version="rf-other"),
        attempt("health", model_version="baseline-a", model_sha256="b" * 64),
        attempt("health", status=503),
    ]
    result = compute(rows, EXPECTED)["identity_match"]
    # The 503 reports no identity; the wrong checksum on /health is a mismatch.
    assert (result["good"], result["eligible"]) == (1, 3)


def test_nearest_rank_quantiles():
    values = [float(v) for v in range(1, 21)]
    assert SIGNALS["nearest_rank"](values, 0.50) == 10.0
    assert SIGNALS["nearest_rank"](values, 0.95) == 19.0
    assert SIGNALS["nearest_rank"]([], 0.95) is None


def test_replay_quality_refuses_held_test_rows():
    rows = [attempt("valid", prediction=1.0, model_version="a", instant=TEST_INSTANT)]
    with pytest.raises(SystemExit, match="outside"):
        compute(rows)


def test_events_are_read_from_local_logs_and_cloud_logging(tmp_path):
    line = {
        "timestamp": "2026-11-13T09:00:00+00:00",
        "event": "request_completed",
        "route": "/predict",
        "status": 200,
        "model_version": "baseline-a",
    }
    local = tmp_path / "local.log"
    local.write_text("INFO:     Started server\n" + json.dumps(line) + "\n")
    cloud = tmp_path / "cloud.json"
    cloud.write_text(json.dumps([{"jsonPayload": line}, {"textPayload": "x"}]))
    for path in (local, cloud):
        summary = SIGNALS["summarize_events"](SIGNALS["read_events"](path))
        assert summary["predict_requests_by_version_and_class"] == {
            "baseline-a | 2xx": 1
        }


def test_probe_cohort_is_validation_only_and_never_sends_labels():
    cohort = PROBE["cohort"](DATA, 30, 8)
    assert len(cohort) == 30
    assert all(set(item["payload"]) == set(FEATURES) for item in cohort)
    first, last = (8646, 13003)  # instants of 2012-01-01 00h and 2012-06-30 23h
    assert all(first <= item["instant"] <= last for item in cohort)
    assert WINDOWS["validation"] == ("2012-01-01", "2012-06-30")
    assert PROBE["cohort"](DATA, 30, 8) == cohort


def test_probe_interleaves_every_population_across_the_window():
    plan = PROBE["attempts"]([{"instant": i} for i in range(6)], 3, 3)
    kinds = [kind for _, (kind, _) in plan]
    assert len(kinds) == 12
    assert kinds[:4].count("valid") == 2
    assert {"invalid", "health"} <= set(kinds[:4])


def test_every_probe_mutation_is_rejected_by_the_api(tmp_path):
    template = PROBE["cohort"](DATA, 1, 8)[0]["payload"]
    with TestClient(create_app(tmp_path / "no-model")) as client:
        assert client.post("/predict", json=template).status_code == 503
        for name, mutate in PROBE["MUTATIONS"]:
            response = client.post("/predict", json=mutate(template))
            assert response.status_code == 422, name


def test_unreachable_service_is_recorded_as_an_attempt_without_status():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    result = PROBE["call"](f"http://127.0.0.1:{port}", "/health", 1.0)
    assert result["status"] is None
    assert result["error"]
    assert result["duration_ms"] >= 0


def test_probe_and_signals_never_overwrite_evidence(tmp_path, capsys):
    out = tmp_path / "probe.jsonl"
    out.write_text("")
    assert (
        PROBE["main"](["http://127.0.0.1:1", "--period", "x", "--out", str(out)]) == 65
    )
    signals_out = tmp_path / "signals.json"
    signals_out.write_text("{}")
    assert SIGNALS["main"]([str(out), "--out", str(signals_out)]) == 65
