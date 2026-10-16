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
49 passing tests and a separate model, baseline-9bc4824e1d60. Its test log
was removed from main and the referenced run and missing-lock logs are absent.
Those results have not been independently verified here. Lab 4 uses the
local model identified below, not that separate artifact.

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
by Git. Their owner still needs to document where teammates can obtain them.

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


## Remaining work

- Open the Lab 4 PR with the implementation, evidence and smoke script.
- Each member must submit a PR for their contribution and review another member.
  The review must include an invalid request and a missing-model case.
- Merge only after human approval and successful checks.
- Create the annotated m2 tag on the integration commit covering Labs 3 and 4,
  then add its link and a short release note here.
- Document how teammates can retrieve the trusted model and metadata.
- Write the individual reports/week-2.md on main in the personal repository,
  without a PR or CI. Include the actual contribution, one decision, one blocker
  and assistance used.

Human reviews, the m2 tag and the individual report have not been completed
or verified in this session.

# Week 2, Lab 3: team evidence

## Team and roles

Team: Vanta. Members: Jeromsan JUDES RAMESH, Merwane KHELOUFI and Yvan
FEUGANG. Jeromsan implemented the Lab 3 changes and ran the local/container
checks. Lab 1 named Merwane KHELOUFI as reviewer; an independent review and a
rerun by a non-author have not been evidenced for Lab 3.

## Repository and pull request

Repository: https://github.com/Jeromsan/mlops-fri1-vanta-bike-demand.
The Lab 3 changes were submitted on branch `lab3` as PR [#2](https://github.com/Jeromsan/mlops-fri1-vanta-bike-demand/pull/2)
and merged into `main` on 2026-10-16. The image was built from source commit
`df79631140a982233ee5b2e324d88f7887db74e3`, which is the PR head commit.

The infrastructure check passed on the PR head. GitHub records an approval
from the repository owner/PR author, but no review threads or actionable
observation from another member. Treat the independent-review requirement as
pending rather than claiming a teammate review.

## Locked dependencies and clean build

`uv.lock` remained unchanged. Its SHA-256 is
`8d84120008104540172043b5dc103a83a3827f42dc8f0f369f0367e32e8c7462`.
`uv lock --check` passed on the project checkout. In disposable copies,
`uv lock --check` rejected both a missing lock and a stale lock; neither copy
was repaired.

The Dockerfile pins `python:3.12.11-slim-bookworm` and `uv:0.12.23`, installs
from the committed lock with `--locked`, and receives the source commit as a
build argument. The build ran with `--no-cache` from a clean checkout of the
recorded commit:

```text
docker build --no-cache --progress=plain --build-arg SOURCE_COMMIT=df79631140a982233ee5b2e324d88f7887db74e3 -t bike-demand:lab3 <clean-checkout>
```

Build result: passed. Image ID:
`sha256:8ace904866a3c1122d13b8ac4a266ae42b243d42e315c80fc5398b04a661d540`.
The `.dockerignore` excludes Git metadata, local environments, credentials,
generated model/tracking output and prior Lab 2 screenshots while retaining
the project files required by preflight and tests. The unedited command output
is saved in [week-02-docker-build.log](./week-02-docker-build.log).

For the missing-lock check, a disposable copy of the same committed source had
only `uv.lock` removed. The Docker build failed at `COPY pyproject.toml uv.lock
README.md ./` with `"/uv.lock": not found` (exit 1). The original lock was not
regenerated or removed. The build output is saved in
[week-02-missing-lock-build.log](./week-02-missing-lock-build.log).

## Container tests and baseline rerun

The full test suite ran in a new container with networking disabled:

```text
docker run --rm --network none --entrypoint uv bike-demand:lab3 run --locked pytest -q
49 passed, 1 warning in 150.06s
```

The warning is an MLflow/SQLAlchemy deprecation warning. No tests failed. The
command and output are saved in [week-02-container-tests.log](./week-02-container-tests.log).

The baseline then ran in a separate fresh container, also without networking:

```text
docker run --name bike-demand-lab3 --network none bike-demand:lab3
exit=0
```

It validated the unchanged frozen snapshot (`e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f`),
used the fixed Lab 2 config, and produced the following evidence:

| Predictor | Validation MAE (rentals/hour) | MLflow run ID |
| --- | ---: | --- |
| Training mean | 154.23179306864967 | `3f30d79c5af2496f8649a5e5abc4b3bb` |
| Random Forest | 86.84685685591091 | `d05587ceb68d4030abeb95988fa3f599` |

Model version: `baseline-9bc4824e1d60`. Model SHA-256:
`d24c050e3631d5b4c2feb8cb571bef6382d8c975c42a5c11edd28de78a0b8c07`.
Readback passed: metadata and logged model bytes matched, reloaded validation
MAE was unchanged, and prediction max absolute delta was `0.0`. The run recorded
source commit `df79631140a982233ee5b2e324d88f7887db74e3`. Since Git metadata is
excluded from the image, `working_tree_dirty` is `null`; the explicit
`SOURCE_COMMIT` build argument supplies the revision.

Partition counts and boundaries were unchanged:

| Partition | Rows | Start | End |
| --- | ---: | --- | --- |
| Train | 8645 | 2011-01-01 | 2011-12-31 |
| Validation | 4358 | 2012-01-01 | 2012-06-30 |
| Test | 4376 | 2012-07-01 | 2012-12-31 |

The test partition was counted but never evaluated. The validation MAEs exactly
match the Lab 2 results recorded in [week-01-team.md](./week-01-team.md): the
same frozen data, feature order, fixed config, random seed and locked
dependencies were used. No metric difference was observed.

The full baseline stdout, including both run IDs and readback results, is saved
in [week-02-container-run.log](./week-02-container-run.log). The build identity
is recorded in [week-02-docker-image.txt](./week-02-docker-image.txt).

## Review observation and author's response

PR #2 is merged and its infrastructure check passed. GitHub shows approval by
the PR author/repository owner and no review comments. An actionable observation
from another member and that member's rerun from this README remain pending.

## Contribution and assistance/recovery acknowledgement

Jeromsan implemented the Lab 3 container and documentation changes and ran the
checks. Copilot assisted with the Lab 2 prerequisite implementation, container
setup, debugging and validation. No instructor recovery function was used.

## Blockers and next action

The locked image builds, its tests pass offline, and the baseline rerun matches
the recorded Lab 2 validation metrics. Remaining team actions: obtain and record
an independent review with one actionable finding and author response, and
have a non-author rebuild from this README and rerun the image. These local
results do not claim remote CI beyond the recorded PR check, nor a rerun on a
different machine.

## Screenshots

No Lab 3 screenshots were captured. The build and run logs linked above are
the primary command evidence.
