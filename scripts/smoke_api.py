"""Record actual HTTP responses from an already running API (no training)."""

import argparse
import json
import math
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("url")
parser.add_argument("--expect-unavailable", action="store_true")
args = parser.parse_args()
payload = json.loads(Path("tests/fixtures/predict-valid.json").read_text())


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(
        args.url + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        response = urlopen(req, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return {
            "method": req.get_method(),
            "url": req.full_url,
            "request": body,
            "status": response.status,
            "response": json.loads(response.read()),
        }


for attempt in range(60):
    try:
        health = request("/health")
        break
    except (URLError, RemoteDisconnected):
        if attempt == 59:
            raise
        time.sleep(0.5)
prediction = request("/predict", payload)
invalid = request("/predict", {})
print(
    json.dumps(
        {
            "transport": "HTTP to Docker-published localhost port",
            "health": health,
            "valid": prediction,
            "invalid": invalid,
        },
        indent=2,
        allow_nan=False,
    ),
    flush=True,
)
expected = 503 if args.expect_unavailable else 200
assert health["status"] == prediction["status"] == expected
assert invalid["status"] == 422
if not args.expect_unavailable:
    result = prediction["response"]
    assert math.isfinite(result["prediction"]) and result["prediction"] >= 0
    metadata = json.loads(Path("artifacts/model-metadata.json").read_text())
    assert result["model_version"] == metadata["model_version"]
    assert health["response"]["model_version"] == result["model_version"]
