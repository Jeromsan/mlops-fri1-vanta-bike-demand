# Week 3 — Lab 5

## Deploying and Verifying the Service

I updated the Lab 4 service so that the running container reports which model and source code it uses. I kept the existing `/health` fields and added `model_sha256` and `source_commit`. The hash is calculated from the same model bytes passed to joblib. I did not retrain or replace the model.

I added a `request_completed` event for every HTTP request. Each event is written as a single JSON line containing the UTC timestamp, a generated request ID, the method, route, status, duration, and available deployment identities.

Request bodies, URL parameters, authentication headers, and client addresses are excluded from the logs. Unknown routes appear as `<unmatched>`. Startup events are recorded separately, and Uvicorn access logs are disabled in the image.

I also implemented an external checker that sends HTTP requests from the host. It receives the expected model version, model hash, and source commit as arguments. These values come from the existing Lab 4 artifact record and the commit used to build the image.

The checker verifies readiness, deployment identity, a valid prediction, and the rejection of `hr=24`. Any mismatch produces exit code 1.

## Source and Runtime Configuration

I ran the checks on October 22, 2026, on Windows with Docker Desktop using Linux containers.

The branch was `lab5/service-deployment`, created from `main` at commit `edcc0f717b842b9c5708e3622ce4f88580193a2a`.

| Item | Value |
| --- | --- |
| Source commit used for the build | `baee60a4dd24b4a30deb84320b6b4bc33c0e4def` |
| Docker image ID | `sha256:02615bba3ec726d316b2e73863da6bf8e52dd03a6ea74c5ed29a9ae7f7d30f65` |
| Expected and observed model version | `baseline-df42e666d6d6` |
| Expected and observed model SHA-256 | `fd98ceafc57a5babce61ce703cbf9cb8d1f83c6820b0b34fe30ad1a0fc49c304` |
| Expected and observed source revision | `baee60a4dd24b4a30deb84320b6b4bc33c0e4def` |

No tracked files were modified when I started the build. The `lab/` directory and evidence directory were untracked and excluded from the Docker build context. I added the evidence and this report after the build, so they are not part of the embedded source commit.

For the working deployment, I used `MODEL_DIR=/models`, a read-only model mount, and host address `127.0.0.1:8000`.

For the missing-model scenario, I started the same image on `127.0.0.1:8001` without the model mount.

The container IDs and runtime settings are recorded in [containers.json](lab5-20261022/containers.json).

## Checks I Performed

| Check | Observed result |
| --- | --- |
| Docker build | Exit code 0 |
| Ruff and formatting | Passed |
| Local preflight | Exit code 0 |
| Full local test suite | 205 passed, 2 warnings, exit code 0 |
| Full test suite inside the image without external network access | 205 passed, 2 warnings, exit code 0 |
| Health and deployment identities | HTTP 200 with matching values |
| Valid prediction | HTTP 200 with prediction `149.2911970908957` and the expected model version |
| Invalid input | HTTP 422 |
| Correct deployment check | Exit code 0 |
| Incorrect expected source revision | Exit code 1 with a reported `source_commit` mismatch |
| Missing model, health request | HTTP 503 |
| Missing model, valid prediction request | HTTP 503 |
| Missing model, invalid input | HTTP 422 |
| Normal deployment check against the missing-model service | Exit code 1 |
| Dedicated missing-model scenario check | Exit code 0, confirming the expected failure behavior |
| Targeted image inspection | Model artifacts, tracking outputs, metrics, and the checked private paths were absent |

### Incorrect Expected Revision

I supplied an incorrect expected source commit to the checker. The service continued to answer requests, but the checker reported the identity mismatch and exited with code 1.

This confirmed that a successful HTTP response alone does not make the deployment check pass.

### Missing Model

I started the image without the model mount. The service logged a `model_unavailable` event with `FileNotFoundError` and diagnostic guidance.

Health requests and valid prediction requests returned HTTP 503. Invalid inputs still returned HTTP 422.

The application log did not include a local path or traceback. The dedicated failure check passed because it observed the expected unavailable state. This result does not mean the service was ready to serve predictions.

## Request Log Checks

I checked that the application events were valid JSON and that each saved curl response matched exactly one request event through its request ID.

The working service recorded 9 completed requests:

- 6 responses with HTTP 200
- 3 responses with HTTP 422

The service without a model recorded 13 completed requests:

- 10 responses with HTTP 503
- 3 responses with HTTP 422

The missing-model count includes repeated requests made during the normal checker's bounded startup wait. Its log also contains a separate startup event.

I checked the model hash again after the tests. It had not changed.

## Evidence

I saved the raw execution records in [lab5-20261022](lab5-20261022/).

### Source and Expected Values

- [Source commit](lab5-20261022/source-commit.txt)
- [Git status](lab5-20261022/git-status.txt)
- [Independent expected values](lab5-20261022/expected.json)

### Docker Build

- [Build command](lab5-20261022/build-command.txt)
- [Build output](lab5-20261022/build.log)
- [Build exit code](lab5-20261022/build-exit.txt)
- [Image ID](lab5-20261022/image-id.txt)

### HTTP Requests and Deployment Checks

- [Executed commands and expected exit codes](lab5-20261022/commands.json)
- [Health response](lab5-20261022/health.log)
- [Valid prediction](lab5-20261022/valid.log)
- [Invalid input](lab5-20261022/invalid.log)
- [Successful deployment check](lab5-20261022/check.log)
- [Incorrect expected revision](lab5-20261022/wrong-commit.log)
- [Dedicated missing-model check](lab5-20261022/missing-check.log)
- [Normal check against the unavailable service](lab5-20261022/missing-normal-check.log)

Each checker output has a corresponding `*-exit.txt` file.

### Missing-Model Responses

- [Health response](lab5-20261022/missing-health.log)
- [Valid prediction request](lab5-20261022/missing-valid.log)
- [Invalid input](lab5-20261022/missing-invalid.log)

### Logs and Code Checks

- [Working service logs](lab5-20261022/container.log)
- [Missing-model service logs](lab5-20261022/missing-container.log)
- [JSON log checks and final model hash](lab5-20261022/log-audit.json)
- [Ruff](lab5-20261022/ruff-check.log)
- [Formatting](lab5-20261022/ruff-format.log)
- [Preflight](lab5-20261022/preflight.log)
- [Local tests](lab5-20261022/local-tests.log)
- [Tests inside the image](lab5-20261022/container-tests.log)
- [Targeted image inspection](lab5-20261022/image-audit.log)
- [Container cleanup](lab5-20261022/cleanup.log)

I ran the Docker, curl, and uv commands from PowerShell. A small Python runner saved their standard output, error output, and exit codes. The executed arguments are included in the evidence files.

I did not use screenshots.

## Decisions

I kept the model outside the image so that the approved model and metadata can be mounted without rebuilding the application.

I checked both the model version and its SHA-256 hash. A version name alone would not identify the actual file loaded by the service.

I limited the published ports to localhost and mounted the model directory read-only.

I kept the HTTP service available when the model could not load. Returning HTTP 503 makes the problem observable and distinguishes a running process from a service that is ready to make predictions.

I documented the ten required deployment decisions and their alternatives in the README's “Deploy — Lab 5” section.

No additional dependency or lock file change was needed.

## Observations and Limitations

I reused the Lab 4 model. Its metadata records training from a modified working tree, so the training commit does not fully identify the code used to produce it. I kept this provenance limitation documented and did not regenerate the model.

The regression tests train isolated test fixtures. They do not replace the team model. I did not calculate metrics on the held-out test period.

The first API test attempt was blocked by permissions on the Windows temporary directory. After resolving the execution permissions, I reran the suite successfully.

The local test output includes a connection interruption from a test HTTP server using a 0.1-second timeout. The suite still finished with 205 passing tests. This message did not appear in the container test run.

The two deprecation warnings concern TestClient and SQLAlchemy. I did not disable assertions to make the tests pass.
