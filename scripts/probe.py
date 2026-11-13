"""External probe: send a fixed, declared workload and keep every attempt raw.

    uv run --locked python scripts/probe.py http://127.0.0.1:8000 \
        --period baseline --out reports/lab8/drill/probe-baseline.jsonl

Three populations, kept apart so one never hides another:

    valid    known-valid /predict requests built from validation-period rows
             (Jan-Jun 2012); only the 12 features are sent, never cnt
    invalid  deliberate contract violations; a 4xx is the correct answer
    health   GET /health readiness probes

The cohort is chosen by --seed, so baseline, incident and recovery replay the
same inputs. Timeouts and connection errors are written as attempts with
status null: they are failures the service logs never see. One JSON line per
attempt; an existing output file is never overwritten.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from bike_demand.split import split_data
from bike_demand.validate import FEATURES, load_data

ROOT = Path(__file__).resolve().parents[1]
# Each mutation breaks one rule of the request contract.
MUTATIONS = (
    ("hr_out_of_range", lambda p: {**p, "hr": 24}),
    ("season_out_of_range", lambda p: {**p, "season": 0}),
    ("temp_not_normalised", lambda p: {**p, "temp": 1.5}),
    ("label_as_input", lambda p: {**p, "cnt": 100}),
    ("missing_field", lambda p: {k: v for k, v in p.items() if k != "hum"}),
    ("string_type", lambda p: {**p, "weathersit": str(p["weathersit"])}),
)


def cohort(data: Path, size: int, seed: int) -> list[dict]:
    validation = split_data(load_data(data))["validation"]
    rows = validation.sample(n=size, random_state=seed).sort_values("instant")
    return [
        {
            "instant": int(row["instant"]),
            "payload": {
                name: float(row[name])
                if name in ("temp", "atemp", "hum", "windspeed")
                else int(row[name])
                for name in FEATURES
            },
        }
        for _, row in rows.iterrows()
    ]


def call(url: str, path: str, timeout: float, body=None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = Request(
        url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"}
    )
    sent_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    result = {"sent_at": sent_at, "status": None, "error": None, "request_id": None}
    try:
        try:
            response = urlopen(req, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            result["status"] = response.status
            result["request_id"] = response.headers.get("X-Request-ID")
            raw = response.read()
        try:
            result["body"] = json.loads(raw)
        except ValueError:
            result["error"] = "non_json_body"
    except Exception as error:  # timeout, refused, reset: the caller saw a failure
        result["error"] = type(error).__name__
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


def attempts(valid: list[dict], invalid: int, health: int):
    """Interleave the three populations so each spans the whole window."""
    populations = {
        "valid": valid,
        "invalid": list(range(invalid)),
        "health": list(range(health)),
    }
    plan = [
        ((index + 0.5) / len(items), kind, item)
        for kind, items in populations.items()
        for index, item in enumerate(items)
    ]
    plan.sort(key=lambda entry: entry[0])
    return [(step, (kind, item)) for step, (_, kind, item) in enumerate(plan)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--period", required=True, help="baseline, incident, ...")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--valid", type=int, default=60)
    parser.add_argument("--invalid", type=int, default=12)
    parser.add_argument("--health", type=int, default=12)
    parser.add_argument("--seed", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--pause", type=float, default=0.05, help="seconds between")
    parser.add_argument("--data", type=Path, default=ROOT / "data/raw/hour.csv")
    args = parser.parse_args(argv)
    parsed = urlsplit(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        parser.error("URL must be HTTP(S)")
    if min(args.valid, args.invalid, args.health) < 1:
        parser.error("each population needs at least one attempt")
    if args.out.exists():
        print(f"{args.out} exists; evidence is never overwritten", file=sys.stderr)
        return 65
    args.out.parent.mkdir(parents=True, exist_ok=True)
    valid = cohort(args.data, args.valid, args.seed)
    template = valid[0]["payload"]
    common = {"period": args.period, "target": args.url, "seed": args.seed}
    with args.out.open("x") as out:
        for step, (kind, item) in attempts(valid, args.invalid, args.health):
            if kind == "valid":
                record = {"kind": kind, "instant": item["instant"]}
                result = call(args.url, "/predict", args.timeout, item["payload"])
            elif kind == "invalid":
                name, mutate = MUTATIONS[item % len(MUTATIONS)]
                record = {"kind": kind, "mutation": name}
                result = call(args.url, "/predict", args.timeout, mutate(template))
            else:
                record = {"kind": kind}
                result = call(args.url, "/health", args.timeout)
            body = result.pop("body", None)
            if isinstance(body, dict):
                for field in ("prediction", "model_version", "model_sha256"):
                    if field in body:
                        record[field] = body[field]
                if "source_commit" in body:
                    record["source_commit"] = body["source_commit"]
            out.write(json.dumps({**common, "step": step, **record, **result}) + "\n")
            out.flush()
            time.sleep(args.pause)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
