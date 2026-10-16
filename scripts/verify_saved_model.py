"""Read-only check of an existing evaluated model; no training or held-test score."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sklearn.metrics import mean_absolute_error

from bike_demand.api import create_app, load_artifact
from bike_demand.preflight import sha256
from bike_demand.split import split_data
from bike_demand.validate import FEATURES, load_data

root = Path.cwd()
directory = root / "artifacts"
metadata = json.loads((directory / "model-metadata.json").read_text())
metrics = json.loads((root / "reports/metrics.json").read_text())
loaded = load_artifact(directory)
for key in ("model_version", "model_sha256", "model_run_id", "features", "data_sha256"):
    if metadata[key] != metrics[key]:
        raise ValueError(f"saved artifact and evaluation record differ: {key}")
data = root / "data/raw/hour.csv"
if sha256(data) != metadata["data_sha256"]:
    raise ValueError("evaluation snapshot differs from artifact metadata")
validation = split_data(load_data(data))["validation"]
predictions = loaded.model.predict(validation.loc[:, list(FEATURES)])
mae = float(mean_absolute_error(validation["cnt"], predictions))
if abs(mae - metrics["validation_mae"]["random_forest"]) > 1e-10:
    raise ValueError("saved model validation MAE differs from recorded evaluation")
payload = {
    "season": 1,
    "yr": 0,
    "mnth": 1,
    "hr": 12,
    "holiday": 0,
    "weekday": 2,
    "workingday": 1,
    "weathersit": 1,
    "temp": 0.5,
    "atemp": 0.5,
    "hum": 0.5,
    "windspeed": 0.0,
}
with TestClient(create_app(directory)) as client:
    response = client.post("/predict", json=payload)
    if response.status_code != 200:
        raise ValueError(response.text)
    print(
        json.dumps(
            {
                "transport": "local TestClient (not Docker or remote CI)",
                "artifact_sha256": sha256(directory / "model.joblib"),
                "model_version": loaded.version,
                "training_commit": metadata["training_commit"],
                "training_working_tree_dirty": metadata["working_tree_dirty"],
                "validation_mae_recomputed": mae,
                "validation_mae_recorded": metrics["validation_mae"]["random_forest"],
                "request": payload,
                "status_code": response.status_code,
                "response": response.json(),
                "health": client.get("/health").json(),
                "invalid_request_status": client.post("/predict", json={}).status_code,
            },
            indent=2,
            allow_nan=False,
        )
    )
