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

## CI — Lab 6

The GitHub Actions workflow runs on pull requests targeting `main`, pushes to
`main`, and manual dispatch. On a clean Ubuntu runner it installs only from the
committed lock file, checks the frozen-data preflight, runs Ruff lint and format
checks, runs the complete test suite, then builds the Docker image without
pushing it. The order puts fast checks before tests and the container build so
the first failure is easier to diagnose.

Reproduce the checks locally from the repository root:

```bash
uv sync --locked
uv run --locked python -m bike_demand.preflight
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
docker build --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" -t bike-demand:ci .
```

CI verifies code, tests, and that the image builds. It does not evaluate model
quality on the held-out test period, verify a live Cloud Run deployment, or
certify behavior on operating systems other than its Ubuntu runner.

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

## Pipeline and gate — Lab 7

One command turns declared, committed inputs into a decided candidate. A
separate, manual command is the only way a candidate becomes the accepted
model. Code: [`pipeline.py`](src/bike_demand/pipeline.py) (stages and CLI),
[`gate.py`](src/bike_demand/gate.py) (policy and outcome rules),
[`store.py`](src/bike_demand/store.py) (accepted-state boundary).

| What | Where |
| --- | --- |
| Policy, committed before any candidate existed | [`configs/gate-policy.yaml`](configs/gate-policy.yaml) (`gate-v1`) |
| Evidence used to size the thresholds | [`reports/lab7/seed-variation.json`](reports/lab7/seed-variation.json), [`reports/lab7/serving-memory.json`](reports/lab7/serving-memory.json) |
| Candidates and their hypotheses | [`configs/candidates/`](configs/candidates/) |
| Decision records (one per run, committed) | [`reports/decisions/`](reports/decisions/) |
| Pointer changes: adopt, promote, restore | [`reports/promotions/`](reports/promotions/) |
| Team report | [Lab 7 section of `reports/week-04-team.md`](reports/week-04-team.md) |

Model binaries, the accepted store (`artifacts/`) and the MLflow database
(`tracking/`) stay out of Git. Commit order shows that the policy
(`git log -- configs/gate-policy.yaml`) precedes the candidate configs, which
precede every decision record.

### What we found in the existing system

| Question | Finding |
| --- | --- |
| Training boundary | `train.py` validates the snapshot, fits on 2011 only, scores the train mean and the RF on Jan–Jun 2012 and never scores the held test. We reuse its `compare_mean` and `select_features` unchanged. |
| Overwrite risk | `python -m bike_demand.train` writes straight to `artifacts/model.joblib`, the API's default `MODEL_DIR`. Before Lab 7, any training run replaced the served model before anyone decided. The pipeline never writes there: candidates go to `artifacts/candidates/<version>/`, and the API is pointed at `artifacts/accepted/<version>/` explicitly. |
| Settings guard | `load_config` only accepts the Week 1 preset, which made any candidate impossible. We left that guard on the legacy command and added a separate one for candidates: data path and the 12 ordered features are checked in code, and model settings must sit inside the bounds of the committed policy (`random_state` 42 and `n_jobs` 1 fixed). Changing a bound means changing the policy, through review. |
| Promotion API / registry | None existed. MLflow records runs but is not a registry here; `artifacts/accepted/CURRENT.json` is the single reference to the accepted version. |

### Pipeline boundary

| Question | Choice | Rejected alternative and reason |
| --- | --- | --- |
| stage | Seven stages in one process: identity (policy, Git), data checks, candidate config + budget, fit, byte and incumbent integrity, quality + operation, tracking. Each stage consumes the previous outputs and produces named check results. | One container or job per stage: no operational need at this size, and the handoffs would need durable addresses we do not have. |
| entry point | `uv run --locked python -m bike_demand.pipeline run --candidate configs/candidates/<name>.yaml`. A clean checkout needs the lock, the frozen CSV, and an adopted incumbent under `artifacts/accepted/` (not in Git, see recovery). | A notebook or a chain of shell commands: no single place where inputs are declared and checked. |
| failure | Every run is a new candidate with a new version id; nothing is overwritten, so a crashed or transient run is retried by running it again. A measured rejection is not retried: it is recorded. Blocked runs before fitting do not consume the budget. | Retrying until green: it would turn a rejection into a search over the validation window. |
| partial | Candidates are written to `candidates/.partial-<version>/` and renamed only when complete; partial directories are never evaluated or promoted and `status` lists them for cleanup. | Writing in place: a crash would leave a half-written model that looks complete. |
| identity | A run is determined by the Git commit (source must be clean), the policy bytes, the candidate config bytes, the data snapshot SHA-256, `uv.lock` and the incumbent's version + digest. All are recorded in the decision. | Run name or timestamp only: says when, not what. |

### Fair comparison

| Question | Choice | Rejected alternative and reason |
| --- | --- | --- |
| reference | The incumbent is whatever `CURRENT.json` names, verified by SHA-256 before loading and recorded in the decision. | "Latest model" or a hard-coded file: the reference must be the one we could roll back to. |
| observations | Candidate, incumbent and train mean are scored in the same run on the same 4,358 validation rows; the decision records a digest of their `instant` ids and labels. | Reusing the incumbent's old score: it could come from another snapshot or code. |
| metric | MAE in rentals per hour on Jan–Jun 2012, lower is better. | RMSE: it would weight a few peak errors more; we chose before scoring, as the lecture asks. |
| margin | 1.0 rental/h vs the incumbent: refitting the accepted settings with ten seeds moved MAE over 0.69 rental/h, and one rental is the smallest unit a rebalancing decision acts on. 30 rentals/h vs the train mean as a floor. | Any improvement (> 0): a seed change alone would "pass". |
| provenance | Old scores are never reused. The incumbent is re-scored from its retained bytes, and comparability requires the same data SHA-256 and feature order in its metadata. | Trusting a stored metric: unavailable matching evidence cannot be claimed as passed. |

### The gate

All three groups are required; the full rule set and the reasoning behind
each threshold are in [`configs/gate-policy.yaml`](configs/gate-policy.yaml).

| Group | Rules (gate-v1) |
| --- | --- |
| Quality | beats the train mean by ≥ 30 rentals/h and the incumbent by ≥ 1.0 rental/h, same rows |
| Operation | loads through the API's own loader (checksum, feature order, probe); model file ≤ 64 MiB; p95 single-request inference ≤ 50 ms over 200 requests |
| Integrity | clean committed source/policy/config; snapshot and data contract; 8645/4358/4376 rows; settings in bounds; budget of 3; candidate bytes unchanged between write and evaluation; verified, comparable incumbent; finite numbers; finished MLflow run |

### What failure means

| Question | Choice | Rejected alternative and reason |
| --- | --- | --- |
| invalid | Non-finite numbers, booleans as numbers, unexpected row counts, changed bytes, dirty source: integrity fails, outcome `blocked`. | Treating them as a low score: a broken measurement says nothing about the model. |
| missing | A required check that did not run is recorded as `not_run` with the reason; any `not_run`, `error` or absent check makes the outcome `blocked`. | Skipping it: "unavailable checks are not passed checks". |
| reject | All evidence is valid and a quality or operation rule failed: outcome `rejected`, reasons list each failed rule with observed value and threshold. | Promoting on better MAE alone: a model that cannot be served is not better. |
| blocked | The reasons name what to repair (commit the change, adopt an incumbent, restore the bytes) before a new run. | Retrying the same run unchanged. |
| status | Exit code 0 eligible, 2 rejected, 3 blocked, 1 crash or usage error. CI runs `pipeline verify-records`, which recomputes every committed outcome from its recorded checks and fails the build if a record was edited. | One exit code for "not promoted": CI could not tell a rejection from a broken run. |

### Accepted-state boundary

| Question | Choice | Rejected alternative and reason |
| --- | --- | --- |
| separate | Candidates may write only under `artifacts/candidates/`. Only `promote`, `adopt` and `restore` write under `artifacts/accepted/`, and only after their checks pass. | One `artifacts/` folder for everything: that was the overwrite risk. |
| identity | A version id (`rf-<12 hex>` or the adopted `baseline-…`) and the SHA-256 of its bytes never change. Accepted files are made read-only. Approval changes the pointer, not the name. | Renaming the winner `model-latest`: the identity would move with the label. |
| switch | Under `accepted/.lock`: check the incumbent, copy into `.partial-<version>`, verify the copy, rename it to `<version>`, then replace `CURRENT.json` in one atomic rename and append `history.jsonl`. If it stops before the rename, `CURRENT` is unchanged; rerunning reuses identical bytes. | Copying over the served file: a crash halfway leaves a corrupt model in service. |
| concurrent | Compare-and-swap: promotion refuses if `CURRENT` no longer names the incumbent the decision was evaluated against, before anything is copied. A second promoter running at the same time fails on the lock instead of waiting. | Last writer wins: a stale decision could replace a newer accepted model. |
| retain | Every accepted version stays under `accepted/<version>/` and in `gs://<bucket>/accepted/<version>/`, with its own Cloud Run revision. `pipeline restore --version <v>` moves the pointer back without retraining. | Deleting the replaced model: Lab 8 recovery would need retraining. |

Promotion also refuses a decision that is not `eligible`, a decision record
that is not committed (reviewed), a policy whose bytes changed since the
decision, candidate bytes that differ from the evaluated bytes, and any
branch other than `main`.

### Run it

From a clean checkout of reviewed `main`, on the machine that holds the
accepted model (PowerShell, macOS or Linux; one line per command):

```bash
uv sync --locked
# Once: register the approved Lab 4/5 artifact as the first accepted version.
uv run --locked python -m bike_demand.pipeline adopt --from artifacts --expected-version baseline-df42e666d6d6 --expected-sha256 fd98ceafc57a5babce61ce703cbf9cb8d1f83c6820b0b34fe30ad1a0fc49c304 --approved-by "<name>" --note "Approved Lab 4/5 artifact; trained from a dirty tree (provenance limitation kept)"
uv run --locked python -m bike_demand.pipeline status
# One run per candidate; the exit code is the outcome (0/2/3).
uv run --locked python -m bike_demand.pipeline run --candidate configs/candidates/c1-deeper-trees.yaml
uv run --locked python -m bike_demand.pipeline status
uv run --locked python -m bike_demand.pipeline verify-records
```

Wrap each command with `scripts/record.py` to keep its raw output and exit
code (see the team report). Commit `reports/decisions/` and
`reports/promotions/` through a PR. Only an `eligible` decision, merged to
`main`, can be promoted:

```bash
uv run --locked python -m bike_demand.pipeline promote --decision reports/decisions/<file>.json --approved-by "<reviewer>"
```

### Serve the accepted version on Cloud Run

Each accepted version is uploaded once to an immutable bucket path and served
by its own revision; the image stays the Lab 5 image, the model stays outside
it (same decision as Lab 5). Commands are printed first; add `--execute` to run
them.

```bash
python scripts/cloud_run_release.py setup    --project <p> --service <s> --bucket <b>
python scripts/cloud_run_release.py upload   --project <p> --service <s> --bucket <b>
python scripts/cloud_run_release.py deploy   --project <p> --service <s> --image <image built from reviewed main>
python scripts/smoke_api.py <tag URL> --expected-version <v> --expected-sha256 <sha> --expected-commit <image commit>
python scripts/cloud_run_release.py traffic  --project <p> --service <s> --revision <new revision>
python scripts/cloud_run_release.py describe --project <p> --service <s>
```

The service account needs `roles/storage.objectViewer` on the bucket. If the
service requires authentication, check the tag through
`gcloud run services proxy <s> --region europe-west1 --tag <tag> --port 8081`
and run the smoke check against `http://127.0.0.1:8081`. The deploy step uses
`--no-traffic`, so the identity check runs before any user reaches the new
revision; the previous revision keeps serving until `traffic` moves it.

### Recovery without retraining (input for Lab 8)

1. `pipeline status`: `current_bytes_verified` and `previous_bytes_verified`
   must be `true`; `accepted_state_sha256` identifies the whole accepted state.
2. Model: `pipeline restore --version <previous> --approved-by <name> --reason <why>`.
3. Service: `cloud_run_release.py traffic --revision <revision that served it>`,
   then `smoke_api.py` against the service URL with that version's identity.
4. If `artifacts/` is lost on the custodian's machine, download
   `gs://<bucket>/accepted/<version>/` and check `model_sha256` against
   `acceptance.json` and the decision record before using it.

### Local and CI claims

Decisions, promotions and latency numbers are local claims: they come from the
machine that holds the accepted model, its `tracking/` store and its
`artifacts/`. A CI runner has none of these, so CI trains nothing and promotes
nothing. CI does check the code (all `lab7` tests run the gate on a small
committed fixture project), and it recomputes every committed decision. Cloud
Run evidence comes only from the live tag and service URLs.

### What this gate still cannot know

It decides on one validation window. It cannot see 2012 growth that the
training year never contained (the accepted model under-predicts validation
demand by about 82 rentals/h on average, which no tree setting can fix with the
fixed feature contract), future weather, behaviour under real Cloud Run load,
or whether repeated candidates have started to overfit Jan–Jun 2012.
