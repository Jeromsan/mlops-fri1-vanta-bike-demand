"""Compute the Lab 8 signals for one period, with the same definitions every time.

    uv run --locked python scripts/signals.py reports/lab8/drill/probe-baseline.jsonl \
        --events reports/lab8/drill/events-baseline.log \
        --expected reports/lab8/drill/expected.json \
        --out reports/lab8/drill/signals-baseline.json

Every ratio is good / eligible over the attempts in the probe file, and the
window is the first and last attempt time in that file. Zero eligible attempts
gives ratio null ("no evidence"), never 100%. Definitions:

    prediction_success  eligible: known-valid /predict attempts, including
                        timeouts and connection errors (status null)
                        good: 200 with a finite, nonnegative prediction and a
                        nonempty model_version
    invalid_rejection   eligible: deliberate contract violations
                        good: any 4xx (a 200 or 5xx is bad)
    readiness           eligible: /health probes; good: 200 (usable model loaded)
    identity_match      eligible: 200 answers that report an identity
                        good: model_version (and model_sha256 on /health)
                        equal to the independently retained --expected record
    latency             nearest-rank p50/p95 in ms, successful and failed
                        known-valid attempts reported separately, with n
    replay_quality      MAE (rentals/h) of successful known-valid predictions
                        against cnt of the same validation-period rows, with
                        coverage; a replay check, not live outcomes

--events reads the service's own structured events (local stderr lines or a
`gcloud logging read --format=json` array) for the same period.
"""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

from bike_demand.split import WINDOWS, split_data
from bike_demand.validate import load_data

ROOT = Path(__file__).resolve().parents[1]


def ratio(good: int, eligible: int) -> dict:
    return {
        "good": good,
        "eligible": eligible,
        "ratio": round(good / eligible, 4) if eligible else None,
        "note": None if eligible else "no evidence",
    }


def nearest_rank(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(quantile * len(ordered))) - 1]


def latency(values: list[float]) -> dict:
    return {
        "n": len(values),
        "method": "nearest-rank",
        "p50_ms": nearest_rank(values, 0.50),
        "p95_ms": nearest_rank(values, 0.95),
    }


def good_prediction(row: dict) -> bool:
    value = row.get("prediction")
    return (
        row.get("status") == 200
        and type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0
        and bool(row.get("model_version"))
    )


def read_events(path: Path) -> list[dict]:
    text = path.read_text()
    if text.lstrip().startswith("["):
        # gcloud logging read --format=json: Cloud Run parses JSON stdout lines.
        return [
            entry["jsonPayload"]
            for entry in json.loads(text)
            if isinstance(entry.get("jsonPayload"), dict)
        ]
    events = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue  # uvicorn startup lines and other plain text
        if isinstance(item, dict) and "event" in item:
            events.append(item)
    return events


def summarize_events(events: list[dict]) -> dict:
    predict = [
        e
        for e in events
        if e.get("event") == "request_completed" and e.get("route") == "/predict"
    ]
    by_identity = Counter(
        f"{e.get('model_version')} | {str(e.get('status'))[0]}xx" for e in predict
    )
    stamps = sorted(e["timestamp"] for e in events if "timestamp" in e)
    return {
        "events": len(events),
        "window": {"first": stamps[0], "last": stamps[-1]} if stamps else None,
        "predict_requests_by_version_and_class": dict(sorted(by_identity.items())),
        "model_unavailable": sum(e.get("event") == "model_unavailable" for e in events),
        "model_inference_failed": sum(
            e.get("event") == "model_inference_failed" for e in events
        ),
    }


def replay_quality(rows: list[dict], data: Path) -> dict:
    validation = split_data(load_data(data))["validation"].set_index("instant")
    eligible = [r for r in rows if r["kind"] == "valid"]
    outside = [r["instant"] for r in eligible if r["instant"] not in validation.index]
    if outside:
        # The held test window stays closed: refuse rather than score it.
        raise SystemExit(f"instants outside {WINDOWS['validation']}: {outside[:5]}")
    matched = [r for r in eligible if good_prediction(r)]
    errors = [
        abs(r["prediction"] - validation.at[r["instant"], "cnt"]) for r in matched
    ]
    return {
        "window": "validation " + " to ".join(WINDOWS["validation"]),
        "matched": len(matched),
        "eligible": len(eligible),
        "coverage": round(len(matched) / len(eligible), 4) if eligible else None,
        "mae": round(sum(errors) / len(errors), 3) if errors else None,
        "mean_prediction": round(
            sum(r["prediction"] for r in matched) / len(matched), 3
        )
        if matched
        else None,
    }


def compute(rows: list[dict], expected: dict | None, data: Path) -> dict:
    periods = sorted({r["period"] for r in rows})
    valid = [r for r in rows if r["kind"] == "valid"]
    invalid = [r for r in rows if r["kind"] == "invalid"]
    health = [r for r in rows if r["kind"] == "health"]
    stamps = sorted(r["sent_at"] for r in rows)
    result = {
        "period": periods[0] if len(periods) == 1 else periods,
        "target": sorted({r["target"] for r in rows}),
        "window": {"first": stamps[0], "last": stamps[-1], "attempts": len(rows)}
        if stamps
        else None,
        "prediction_success": ratio(sum(map(good_prediction, valid)), len(valid)),
        "invalid_rejection": ratio(
            sum(
                r.get("status") is not None and 400 <= r["status"] < 500
                for r in invalid
            ),
            len(invalid),
        ),
        "readiness": ratio(
            sum(r.get("status") == 200 for r in health),
            len(health),
        ),
        "failures_by_cause": dict(
            Counter(
                str(r.get("status") or r.get("error"))
                for r in valid
                if not good_prediction(r)
            )
        ),
        "invalid_statuses": dict(Counter(str(r.get("status")) for r in invalid)),
        "served_versions": dict(
            Counter(r["model_version"] for r in rows if r.get("model_version"))
        ),
        "served_sha256": dict(
            Counter(r["model_sha256"] for r in health if r.get("model_sha256"))
        ),
        "latency_success": latency(
            [r["duration_ms"] for r in valid if good_prediction(r)]
        ),
        "latency_failed": latency(
            [r["duration_ms"] for r in valid if not good_prediction(r)]
        ),
        "replay_quality": replay_quality(rows, data),
    }
    if expected is not None:
        identified = [
            r
            for r in valid + health
            if r.get("status") == 200 and r.get("model_version")
        ]
        result["identity_match"] = {
            "expected": expected,
            **ratio(
                sum(
                    r["model_version"] == expected["model_version"]
                    and r.get("model_sha256", expected["model_sha256"])
                    == expected["model_sha256"]
                    for r in identified
                ),
                len(identified),
            ),
        }
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("probe", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--expected", type=Path, help="retained identity record")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--data", type=Path, default=ROOT / "data/raw/hour.csv")
    args = parser.parse_args(argv)
    if args.out and args.out.exists():
        print(f"{args.out} exists; evidence is never overwritten", file=sys.stderr)
        return 65
    rows = [json.loads(line) for line in args.probe.read_text().splitlines() if line]
    expected = json.loads(args.expected.read_text()) if args.expected else None
    result = {"probe_file": str(args.probe), **compute(rows, expected, args.data)}
    if args.events:
        result["service_events"] = {
            "file": str(args.events),
            **summarize_events(read_events(args.events)),
        }
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
