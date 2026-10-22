# Bike Demand: Week 1 starter

Teams of 3–4 use one private GitHub repository throughout the course. Lab 1 is
repository setup, Git workflow and quality checks. Lab 2 adds validated data,
chronological splitting, a baseline comparison and local MLflow tracking.
No Docker, cloud account or MLflow server is needed this week.

## Week 2, Lab 4: Prediction API

The service loads a trusted, already evaluated `model.joblib` together with
`model-metadata.json` once during startup. It never trains or repairs artifacts.
Python 3.12 and the committed dependency lock are required.

The verification script reads the existing artifact and evaluation record and
recomputes only validation MAE; it does not fit a model or score the held test.
The default artifact directory is `artifacts`; override it with `MODEL_DIR`.
Obtain the matching, trusted model and metadata from the team's evaluated Lab 2/3
outputs. They are deliberately not committed. A fresh clone needs those two
files before it can serve predictions. Verify `model_sha256` against the model
bytes; startup also checks feature order in the metadata and loaded estimator.
The observed local artifact's identity and provenance limitations are recorded
in [the Week 2 team report](reports/week-02-team.md).

`GET /health` returns 200 only after loading and probing a usable model. Missing,
corrupt or mismatched artifacts leave the service running with 503. Valid
`POST /predict` requests also return 503 in that state. Both routes consult the
same loaded-model state; an inference failure clears it until restart.

`POST /predict` accepts exactly these fields in one flat JSON object:

| Fields | Accepted JSON values |
| --- | --- |
| `season` | integer 1–4 |
| `yr`, `holiday`, `workingday` | integer 0–1 |
| `mnth` | integer 1–12 |
| `hr` | integer 0–23 |
| `weekday` | integer 0–6 |
| `weathersit` | integer 1–4 |
| `temp`, `atemp`, `hum`, `windspeed` | finite number 0–1 inclusive |

Strings, booleans, nulls, missing fields and out-of-range values are rejected
with 422 before request inference. Integer predictors reject fractional numbers
and JSON floating-point values such as `1.0`. Weather accepts JSON integers or
floats, already normalised; no scaling is applied. Every extra field is rejected,
including `cnt`, `casual`, `registered`, `instant` and `dteday`. Predictors are
ordered by the training `FEATURES` contract, regardless of JSON key order.

A valid request example is saved in `tests/fixtures/predict-valid.json`.

A successful response contains `prediction` (finite and nonnegative, rentals per
hour) and `model_version` read from the metadata bound to the loaded model.
Versions and predictions are never hard-coded. `/docs` exposes the schema.

### Container build, tests and serving

Start Docker Desktop with Linux containers. Build from the committed revision,
passing its Git SHA through the `SOURCE_COMMIT` build argument. Run the tests
in the image, record its image ID, and mount the trusted artifacts read-only.

The image listens on `0.0.0.0:8000`; the published host port is limited to
`127.0.0.1`. Artifacts stay outside the image and are mounted read-only.
Send requests to both routes and save the responses and container logs.
Stop and remove the container after verification.

For the no-model review, run the same image without the mount and repeat both
routes: health and a valid prediction must return 503, an invalid request 422.
The automated API tests use synthetic serving fixtures only, without training;
the mounted real artifact is checked separately by the HTTP smoke test.
Keep raw logs, tested source SHA, image ID and actual model version in
`reports/lab4-*`; refer to them from the team report. Local and container runs
are separate from remote CI. No more than three screenshots are needed.

Each member must submit a PR for their actual contribution and review another
member's work, including an invalid request and no-model case. Human review is
not replaced by these tests. After approved PRs and successful checks are merged,
create the annotated `m2` tag on the integration revision covering Labs 3 and 4.
Record its link and a short release note in the team report. Do not tag before
review. The individual `reports/week-2.md` belongs on `main` in the personal
repository, without PR or CI, and must describe actual contribution, a decision,
a blocker and assistance (including Codex).

## Week 2, Lab 3: locked container rerun

The Lab 3 image installs dependencies only from the committed `uv.lock`; the
Docker build and runtime do not regenerate it. Build from a clean checkout with
Docker Desktop running:

```bash
docker build --no-cache --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" -t bike-demand:lab3 .
```

Run this from the clean, committed checkout being evaluated; the build requires
the commit argument so the container can record its source revision without
copying `.git` into the image.

The image contains the frozen CSV, baseline config, source and tests. Run the
tests without network access, then run the Lab 2 baseline in a fresh container,
also without network access:

```bash
docker run --rm --network none --entrypoint uv bike-demand:lab3 run --locked pytest -q
docker run --name bike-demand-lab3 --network none --entrypoint uv bike-demand:lab3 run --locked --no-sync python -m bike_demand.train --config configs/baseline.yaml
docker logs bike-demand-lab3
mkdir -p out
docker cp bike-demand-lab3:/app/artifacts ./out/
docker cp bike-demand-lab3:/app/reports ./out/
docker cp bike-demand-lab3:/app/tracking ./out/
docker rm bike-demand-lab3
```

Save the unedited build and run logs with the outputs. Record the exact source
commit and `uv.lock` hash, Docker build log and image ID, the two validation
MAEs and MLflow run IDs, and the model version. Compare those validation
metrics with the Lab 2 record and explain any difference. Do not score the held
test partition. A local run is not evidence of a remote CI run or a rerun by a
non-author.

To demonstrate that a missing lock fails without repairing it, use a disposable
copy of a clean checkout, remove `uv.lock` in that copy, and run the same Docker
build there. The build must stop at the missing-lock `COPY` step. Do not remove
the lock from the working checkout or run `uv lock` to turn that failure green.
Keep team evidence in [`reports/week-02-team.md`](reports/week-02-team.md).

The base images are pinned to Python 3.12.11 and uv 0.12.23. The application
dependencies and development tools are installed from the committed lock with
`--locked`; source and frozen data are copied only after the dependency layer.
`.dockerignore` excludes local environments, Git metadata, credentials and
generated model/tracking/report outputs from the build context.

## Setup: Lab 1

Install Git and [uv](https://docs.astral.sh/uv/getting-started/installation/)
(`>=0.12.19,<0.13`). Python **3.12** is required; uv can download it. From the
`bike-demand/` root:

```bash
uv python install 3.12
uv sync --locked
uv run --locked python -m bike_demand.preflight
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q -m infra
uv run --locked pytest -q -m lab1
```

First setup requires internet for Python and the locked dependencies, unless
these exact distributions are already cached. The frozen UCI CSV ships here;
preflight does not download/repair it. `uv.lock` is shared across platforms;
that is not evidence that every OS has been tested. macOS setup has been checked;
Windows and Linux remain unverified. Remote CI is unavailable until a permitted
repository is configured and a workflow actually runs on the checked revision.
Do not regenerate the lock just to bypass an installation failure.

## Expected failure and exercise: Lab 1

`pytest -m infra` must pass immediately. `pytest -m lab1` has **one intentional
behavior failure** in `src/bike_demand/team.py`: the helper
`normalize_team_slug` does not yet meet the contract in `tests/lab1/test_team.py`
(trim, lowercase, join whitespace with hyphens, reject blank names with
`ValueError`). Read the assertion, diagnose the cause, make a small repair and add
one useful test of your own. Do not weaken assertions, skip tests or disable
checks. Sync or import errors, or failures outside `lab1`, are setup problems:
diagnose them separately.

Fill in `WORKING-AGREEMENT.md`. Use a task branch, open a pull request, and get a
review from another member before merging. Rotate driver/reviewer roles and the
main PR author between labs. Keep actual evidence in `reports/lab-01.md` and
`reports/week-01-team.md`; templates contain no pre-filled results.

## Expected failures: Lab 2

The student export has bounded TODOs in `src/bike_demand/`:

| File | Your task |
| --- | --- |
| `validate.py` | Categorical domains, finite normalised ranges, nonnegative counts, date windows |
| `split.py` | Chronological nonempty/disjoint/complete partitions; sort `(dteday, hr, instant)` |
| `train.py` | Ordered predictors, train-mean comparator, RF fit and validation MAE |

`NotImplementedError("TODO(Week 1, Lab 2): ...")` and failing exercise tests are
**expected before implementation**, not environment failures. Infra must pass
immediately. Do not skip/mute exercise tests or fabricate metrics to get green.
Tracking, metadata/history, configuration and input parsing are already supplied.
Read the failing test, inspect the contract, implement one TODO, and rerun:

```bash
uv run --locked pytest -q -m exercise
uv run --locked python -m bike_demand.validate --data data/raw/hour.csv
uv run --locked python -m bike_demand.train --config configs/baseline.yaml
uv run --locked pytest -q
```

Keep `data/raw/hour.csv` unchanged; use copies and `tests/fixtures/` for deliberate
faults. `missing-temp.csv` is the worked Fault A; design your own Fault B by
breaking exactly one contract rule or split boundary on a tiny copy, with a valid
control and a test of your own. The supplied `hum-out-of-range.csv` is another
worked example, not your Fault B. Missing hours are valid. Features and splits are fixed in the config and
code. Fit only on 2011 training rows; compare both predictors on the same
2012 January–June validation rows. Hold July–December 2012 test rows throughout
Weeks 1–4; do not compute test metrics. MAE is rentals/hour, not accuracy, and
RF is not required to beat the comparator. The task uses supplied weather;
it does not forecast future weather or station-level demand.

## Outputs and readback

Each successful train execution creates two separate MLflow runs, a saved
`artifacts/model.joblib` and `model-metadata.json`, latest `reports/metrics.json`,
and one appended `reports/metrics-history.jsonl` line. Metadata records feature
order, data identity, model version and run ID. A commit is recorded when Git is
available; `working_tree_dirty` prevents uncommitted code being mistaken for a
committed revision. Train reloads the trusted local model and verifies validation
MAE/metadata and logged artifact bytes. Never load untrusted joblib files.
Optional stretch, only after the core is complete and reviewed: run train again
unchanged and compare both run IDs and observed MAEs/history. Do not promise
byte-identical models across systems/library versions.

Viewer is optional; training does not depend on it:

```bash
uv run --locked mlflow server --backend-store-uri sqlite:///tracking/mlflow.db --default-artifact-root tracking/artifacts --no-serve-artifacts --host 127.0.0.1 --port 5000 --workers 1
```

`artifacts/`, `tracking/` and `.venv/` are ignored by Git. Team metrics may be
committed as evidence; never commit credentials or individual private reports.
CI currently checks only infrastructure/quality; expand it in Week 3.

## Support and individual reports

If setup remains blocked after five minutes, contact the instructor using the
support route recorded in your working agreement. Do not spend the whole lab
repairing a laptop. Ask for an approved recovery function only if coding remains
blocked; acknowledge the supplied code and assistance in your report. Recovery
is instructor-controlled, not bundled here.

## Names, reports and screenshots

Repository names (lowercase, hyphens, the same for the whole course):

- Team repository: `mlops-<session>-<team-name>-bike-demand`, for example
  `mlops-thu1-sparrows-bike-demand`. Sessions: `thu1`, `thu2`, `fri1`, `fri2`
  (1 = morning, 2 = afternoon).
- Your private report repository: `mlops-<session>-<github-username>`, for example
  `mlops-thu1-minhtc`. You create it and invite the instructor (`minhtc-uca`). Start from the
  [report template](../report-template/README.md) and commit to `main`; no report
  pull request or CI is used.

Reports mix writing and images. Save screenshots in `reports/images/` and embed
them in the report (see the template). A screenshot supports, but does not replace,
the command, revision and your explanation. Never show tokens, passwords or
personal data. Team evidence goes in `reports/lab-01.md` and
`reports/week-01-team.md`, with team screenshots in `reports/images/`.
Each weekly report is due Sunday 23:59 of the same week (published time zone).
Assessment policy comes from the instructor, not this repository.
See `BACKLOG.md` for later labs.

## Deploy — Lab 5

This procedure serves the evaluated Lab 4 model only. It never trains or repairs
artifacts. Work from the repository root. Docker Desktop
must use Linux containers; install Git, Python 3.12 and uv 0.12.x, then run
`uv sync --locked`. Obtain the trusted `model.joblib` and matching
`model-metadata.json` from the team's Lab 4 artifact custodian. A clone alone
cannot serve predictions. Never load an unknown joblib file.

The approved local Lab 4 record is version `baseline-df42e666d6d6`, SHA-256
`fd98ceafc57a5babce61ce703cbf9cb8d1f83c6820b0b34fe30ad1a0fc49c304`.
See `reports/lab4-saved-model-check.json` and `reports/week-02-team.md`.
Its training tree was dirty: its training commit does not fully identify the
training source. We preserve this limitation and reuse the artifact unchanged.

### Prepare independent expectations and build

Use a committed checkout. Review `git status --short`: source, Dockerfile,
README, lock and tests must have no pending changes. An untracked teaching PDF
under `lab/` is excluded from the Docker context. Do not claim a dirty build
matches HEAD. Save new evidence under a new run directory rather than overwriting
an earlier run. Expected values come from the approved artifact record and Git,
never from `/health`.

Dependencies are installed with `uv sync --locked`. No dependency was added for
Lab 5. The image contains source, tests and the public frozen input CSV needed
by infrastructure checks, but no team artifact, tracking store, metrics output
or team report content. The empty Week 1 report path only satisfies preflight's
file-presence check. Docker's build argument records a claim: clean source and
the saved build command are necessary to substantiate it.

Before building, record the full Git commit, clean tracked-file status, model
version and independently computed file SHA-256 under a new `reports/lab5-*`
directory. Compare both artifact identities with the approved record above.
Build the root Dockerfile with `SOURCE_COMMIT` set to that Git commit; tag it
`bike-demand:lab5`. Save the build output, exit code and image ID.
The exact commands used for the recorded run are available in
[the build record](reports/lab5-20261022/build-command.txt) and
[the execution record](reports/lab5-20261022/commands.json).

### Start, check and inspect

Choose free host ports. Keep the container port 8000. `MODEL_DIR` points to the
read-only mount. Use `/models` as the container location and publish host port
8000 on `127.0.0.1` only. Set `MODEL_DIR=/models` at launch.

Run `scripts/smoke_api.py` from the host with the service URL and the
`--expected-version`, `--expected-sha256` and `--expected-commit` arguments.
Use the approved identity above and the source commit recorded before building.
Save its output and exit code. Send the fixture in
`tests/fixtures/predict-valid.json` to `POST /predict`, then an empty JSON object
to the same route. Save these responses and `GET /health`, including headers.
Read and save container logs with Docker Desktop or `docker logs`.

The checker uses only HTTP to contact the service. It waits at most 30 seconds
for readiness (each request has a timeout of at most 5 seconds), checks all three
identities, predicts, then sends `hr=24` and requires 422. Every claim prints
expected, observed and result. Exit 0 means all checks pass; other exits mean
failure. The startup wait plus the two prediction calls is bounded, apart from
operating-system DNS resolution. This localhost procedure avoids DNS.
`--expect-unavailable` checks 503/503/422 only; it does not certify identity.

### Observe deliberate failures and clean up

Keep the same image and correct expectations; first change only the expected
code revision. The checker must return 1 even though the service returns 200.
Then run without a model: health and valid prediction must be 503, invalid
prediction 422. Startup should emit `model_unavailable` without a traceback or
local path. These checks do not change the approved artifact.

Repeat the host check with `--expected-commit deliberately-wrong` and require
exit 1. Start a second container from the same image without the model mount,
with `MODEL_DIR=/models` and host port 8001 restricted to `127.0.0.1`.
Save its HTTP responses and logs. The normal checker must fail;
`--expect-unavailable` is only a diagnostic check of the expected 503/503/422
state. Record image and container IDs, port bindings and read-only mount
configuration. Stop and remove both temporary containers once logs are saved.

### Ten deployment decisions

| Question | Choice | Rejected alternative and reason |
| --- | --- | --- |
| settings | `MODEL_DIR` and read-only mount at launch; host port chosen at launch; source commit at build | Editing Python for each machine would make the same image behave as different source |
| model | Trusted evaluated Lab 4 pair, verified before and during loading | Retraining at startup changes the approved model and violates the lab |
| ready | Model checksum, feature order and finite nonnegative probe pass; inference failure clears readiness | A live HTTP process alone cannot promise predictions |
| broken | Keep HTTP running; health and valid prediction return 503; invalid input stays 422 | Exiting immediately prevents external inspection of the unavailable state |
| log line | One `request_completed` JSON line: UTC time, generated request ID, method, route template, status, duration, model identity and source commit | Raw request dumps leak content and are difficult to correlate |
| secrets | No body, auth header, query, client address, arbitrary unmatched path or exception text; only safe error class for lifecycle events | Tracebacks and full URLs can expose private values |
| identity | Metadata version plus SHA-256 of the exact bytes deserialized, with image source commit | Version labels alone can refer to different bytes |
| expected | Final checker obtains approved identity before launch from the Lab 4 record and source Git commit | Copying expected values from the API makes the comparison circular |
| promise | At check time this image answers locally with the expected code/model, accepts valid input and rejects invalid input | A running container is insufficient; this check promises neither accuracy, availability over time nor production readiness |
| failure | Wrong expected commit fails; absent mount produces 503 and a safe startup event | A simulated failure provides no evidence about the running image |

Application events are JSON with an `event` field. Uvicorn access logs are
disabled; its lifecycle messages are separate non-JSON server messages.
`model_unavailable` and `model_inference_failed` are lifecycle/error events,
not additional request-completion events. Unknown paths are logged as
`<unmatched>` to avoid exposing private path content. Request IDs are generated
by the service rather than trusting client-supplied identifiers.

### Human review and handover

Each actual member needs their own substantive contribution and PR into `main`,
and must review another member's PR. Do not split already completed work into
fictional ownership. The reviewer follows only this section, changes the host port
to a free port (for example 8010), and checks that the HTTP URL and saved port
mapping reflect it. They also verify the non-default `/models` configuration,
the read-only mount, successful identity check and deliberate failures.
Record one actionable finding, the author's response and the actual rerun.

Final check owner: **to be designated by the team before acceptance**.
Record their name, checked commit, image and evidence directory in the team
report. Local tests and Docker HTTP evidence are separate from remote CI.
The current workflow does not certify this Docker deployment. Lab 6 extends CI;
create annotated `m3` only after both Labs 5 and 6 are reviewed and merged.
The individual `reports/week-3.md` belongs on personal `main`, with no PR or CI;
it records actual work, decision, blocker and assistance, including AI help.

Execution status and exact results belong in `reports/week-03-team.md` and its
linked raw logs. This procedure describes the steps; the linked evidence
records the commands and results actually observed.
