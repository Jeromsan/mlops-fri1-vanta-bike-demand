# Week 2: Labs 3 and 4

Repository: https://github.com/Jeromsan/mlops-fri1-vanta-bike-demand

## Lab 3

Lab 3 is available on main through merge commit b8f7937 (PR #2).
It provides a Dockerfile and dependencies installed from uv.lock.
The old container test log records 5 failed and 44 passed tests
(`week-02-container-tests.log`). This was not a successful test run.
The earlier build output is saved in `week-02-docker-build.log`.
No new Lab 3 training run was performed for this report. An updated Lab 3
report from main at 87aa3da is preserved in `week-02-lab3.md`. It records
49 passing tests and a separate model, baseline-9bc4824e1d60. The earlier failed test log is retained here; the successful test log and
the referenced run and missing-lock logs are not available in this checkout.
Lab 4 uses the local model identified below, not that separate artifact.

We reused the saved model in artifacts/model.joblib and its metadata:

- Version: baseline-df42e666d6d6
- Model SHA-256: fd98ceafc57a5babce61ce703cbf9cb8d1f83c6820b0b34fe30ad1a0fc49c304
- MLflow run: f185f6791a2f45d38abd320432dea414
- Training commit: 3b00e6018ac416a1d7d145fe85caa0270cccd231
- Recorded validation MAE: 86.84685685591091 for the random forest,
  compared with 154.23179306864967 for the mean baseline.

The metadata says the training working tree was modified. The commit alone
therefore does not identify all the training code. The saved-model check
reproduced the recorded validation MAE without training or scoring the held-out
test set (`lab4-saved-model-check.json`). The artifact files are ignored
by Git and are stored outside the source repository.

## Lab 4

The FastAPI service loads the existing model at startup. It checks its checksum,
feature order and ability to predict. It reads model_version from the matching
metadata. The service never trains a model.

Both routes use the same model state. GET /health returns 200 when the model
is available and 503 otherwise. POST /predict returns a finite, nonnegative
prediction and the model version, or 503 if the model is unavailable.

We chose to reject all extra fields, including cnt, casual and registered.
Pydantic checks the 12 required fields, their types and their allowed ranges
before request inference. Weather values are already normalized. The API keeps
the training feature order and applies no additional scaling.

## Verification

We tested the Docker image on October 18, 2026.

- Application source commit: 5a53ae61ca1ccbc3480d220698c330629838507e
- Image ID: sha256:05b8751fd2945ca8c7afba659e5a462dc378a91eba72dae4208fa1d4db660daf
- Model version: baseline-df42e666d6d6

The report, new logs and host-side smoke script were uncommitted additions.
The application, tests, Dockerfile and lock used in the image were unchanged
from the source commit above.

The image build succeeded using cached layers
(`lab4-docker-build-current.log`). The previous failed build is kept
in lab4-docker-build.log. We ran the full test suite inside the new image:

```sh
docker run --rm --network none --entrypoint uv bike-demand:lab4 run --locked --no-sync pytest -q
```

Result: **191 passed, 2 warnings in 50.79s**
(`lab4-container-tests.log`). The warnings concern deprecated
TestClient and SQLAlchemy behavior. Baseline tests can train isolated test
fixtures; the API does not train or replace the team model.
The local API suite also passed all 141 tests. Tests use TestClient in a with
block to run startup and shutdown.

We then tested the API through localhost:

| Case | Health | Prediction |
| --- | --- | --- |
| Model available, valid input | 200 | 200 |
| No model, valid input | 503 | 503 |
| Invalid empty input, either model state | - | 422 |

The valid response was:

```json
{"prediction": 149.2911970908957, "model_version": "baseline-df42e666d6d6"}
```

The full request and response are in `lab4-http-model.json`.
The missing-model requests are in `lab4-http-no-model.json`.
The server listened on 0.0.0.0 inside Docker. Host ports were limited to
127.0.0.1 (8000 with the model, 8001 without it). The model was mounted read-only.
Both temporary containers were stopped and removed after verification.

Other evidence: `lab4-image-id.txt`,
`lab4-containers.json`,
`lab4-server-model.log`, and
`lab4-server-no-model.log`.
We did not use screenshots or run remote CI for these checks.


## Integration

Lab 4 PR #3 was merged into main at commit 8632ea1.
The team has confirmed that the reviews and validations are complete.

The annotated m2 release tag is still pending.
