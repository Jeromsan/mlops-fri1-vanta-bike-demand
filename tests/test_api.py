"""Synthetic serving fixtures only; these are not evaluated course models."""

import json

import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from bike_demand.api import create_app
from bike_demand.preflight import sha256
from bike_demand.validate import DOMAINS, FEATURES, NORMALISED

VALID = dict(
    season=1,
    yr=0,
    mnth=1,
    hr=12,
    holiday=0,
    weekday=2,
    workingday=1,
    weathersit=1,
    temp=0.5,
    atemp=0.5,
    hum=0.5,
    windspeed=0.0,
)


class ServingFixture:
    feature_names_in_ = np.array(FEATURES)

    def predict(self, frame):
        assert list(frame.columns) == list(FEATURES)
        return np.array([frame.iloc[0]["hr"] + frame.iloc[0]["temp"]])


@pytest.fixture
def artifact_dir(tmp_path):
    joblib.dump(ServingFixture(), tmp_path / "model.joblib")
    metadata = {
        "model_version": "synthetic-serving-fixture",
        "features": list(FEATURES),
        "model_sha256": sha256(tmp_path / "model.joblib"),
    }
    (tmp_path / "model-metadata.json").write_text(json.dumps(metadata))
    return tmp_path


def test_loaded_model_and_shutdown(artifact_dir):
    app = create_app(artifact_dir)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        result = client.post("/predict", json=VALID)
        assert result.status_code == 200
        assert result.json() == {
            "prediction": 12.5,
            "model_version": "synthetic-serving-fixture",
        }
        # HTTP predictions must come from the loaded object, without disk reloads.
        (artifact_dir / "model.joblib").unlink()
        assert client.post("/predict", json=VALID).status_code == 200
    assert app.state.loaded_model is None


def test_absent_model(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").status_code == 503
        assert client.post("/predict", json=VALID).status_code == 503
        assert client.post("/predict", json={}).status_code == 422


INVALID = []
for field in FEATURES:
    INVALID.append({key: value for key, value in VALID.items() if key != field})
    for value in (None, True, "1", [], {}):
        INVALID.append({**VALID, field: value})
for field, (lower, upper) in DOMAINS.items():
    for value in (lower - 1, upper + 1, 1.0):
        INVALID.append({**VALID, field: value})
for field in NORMALISED:
    for value in (-0.01, 1.01):
        INVALID.append({**VALID, field: value})
for field in ("cnt", "casual", "registered", "instant", "dteday", "other"):
    INVALID.append({**VALID, field: 1})
INVALID.extend([[], [VALID], "invalid", None])


@pytest.mark.parametrize("payload", INVALID)
def test_invalid_input_never_runs_inference(artifact_dir, monkeypatch, payload):
    app = create_app(artifact_dir)
    with TestClient(app) as client:

        def forbidden(*args):
            pytest.fail("invalid request reached inference")

        monkeypatch.setattr(app.state.loaded_model.model, "predict", forbidden)
        assert client.post("/predict", json=payload).status_code == 422


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field", NORMALISED)
def test_nonfinite_weather(artifact_dir, number, field):
    with TestClient(create_app(artifact_dir)) as client:
        body = json.dumps({**VALID, field: "NONFINITE"}).replace('"NONFINITE"', number)
        assert (
            client.post(
                "/predict", content=body, headers={"Content-Type": "application/json"}
            ).status_code
            == 422
        )


@pytest.mark.parametrize("value", [0, 1])
def test_inclusive_weather_boundaries(artifact_dir, value):
    with TestClient(create_app(artifact_dir)) as client:
        payload = {**VALID, **dict.fromkeys(NORMALISED, value)}
        assert client.post("/predict", json=payload).status_code == 200


@pytest.mark.parametrize(
    "fault",
    [
        "missing-metadata",
        "bad-json",
        "checksum",
        "features",
        "version",
        "corrupt-model",
    ],
)
def test_unusable_artifact(artifact_dir, fault):
    path = artifact_dir / "model-metadata.json"
    metadata = json.loads(path.read_text())
    if fault == "missing-metadata":
        path.unlink()
    elif fault == "bad-json":
        path.write_text("{")
    else:
        if fault == "checksum":
            metadata["model_sha256"] = "wrong"
        elif fault == "features":
            metadata["features"] = list(reversed(FEATURES))
        elif fault == "version":
            metadata["model_version"] = ""
        else:
            (artifact_dir / "model.joblib").write_bytes(b"broken")
            metadata["model_sha256"] = sha256(artifact_dir / "model.joblib")
        path.write_text(json.dumps(metadata))
    with TestClient(create_app(artifact_dir)) as client:
        assert client.get("/health").status_code == 503
        assert client.post("/predict", json=VALID).status_code == 503


@pytest.mark.parametrize("output", [float("nan"), float("inf"), -1, [1, 2]])
def test_inference_failure_clears_shared_readiness(artifact_dir, monkeypatch, output):
    app = create_app(artifact_dir)
    with TestClient(app) as client:
        monkeypatch.setattr(
            app.state.loaded_model.model, "predict", lambda frame: [output]
        )
        assert client.post("/predict", json=VALID).status_code == 503
        assert client.get("/health").status_code == 503


def test_lifespan_reloads_into_fresh_state(artifact_dir):
    app = create_app(artifact_dir)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    (artifact_dir / "model.joblib").unlink()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 503
