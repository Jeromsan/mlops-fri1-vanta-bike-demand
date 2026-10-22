"""Check a running deployment using HTTP and independently supplied identities."""

import argparse
import json
import math
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def request(url, path, timeout, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(
        url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        response = urlopen(req, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--request-timeout", type=float, default=5)
    parser.add_argument("--expect-unavailable", action="store_true")
    args = parser.parse_args(argv)
    parsed = urlsplit(args.url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        parser.error("URL must be HTTP(S), without credentials, query or fragment")
    if args.startup_timeout <= 0 or args.request_timeout <= 0:
        parser.error("timeouts must be positive")
    checks = []

    def check(claim, expected, observed):
        ok = type(expected) is type(observed) and expected == observed
        checks.append(ok)
        print(
            json.dumps(
                {
                    "claim": claim,
                    "expected": expected,
                    "observed": observed,
                    "result": "ok" if ok else "FAIL",
                },
                allow_nan=False,
            ),
            flush=True,
        )

    try:
        deadline = time.monotonic() + args.startup_timeout
        expected_status = 503 if args.expect_unavailable else 200
        while True:
            try:
                status, health = request(
                    args.url,
                    "/health",
                    min(args.request_timeout, max(0.001, deadline - time.monotonic())),
                )
                if status == expected_status or time.monotonic() >= deadline:
                    break
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        check("health_status", expected_status, status)
        if not args.expect_unavailable:
            check("ready", "ok", health.get("status"))
            for field, expected in (
                ("model_version", args.expected_version),
                ("model_sha256", args.expected_sha256.lower()),
                ("source_commit", args.expected_commit),
            ):
                check(field, expected, health.get(field))
        payload = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "tests/fixtures/predict-valid.json"
            ).read_text()
        )
        status, prediction = request(
            args.url, "/predict", args.request_timeout, payload
        )
        check("prediction_status", expected_status, status)
        if not args.expect_unavailable:
            value = prediction.get("prediction")
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
            check("finite_nonnegative_prediction", True, valid)
            check(
                "prediction_model_version",
                args.expected_version,
                prediction.get("model_version"),
            )
        status, _ = request(
            args.url, "/predict", args.request_timeout, {**payload, "hr": 24}
        )
        check("invalid_status", 422, status)
    except Exception as error:
        check("http_check_completed", "success", type(error).__name__)
    return 0 if checks and all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
