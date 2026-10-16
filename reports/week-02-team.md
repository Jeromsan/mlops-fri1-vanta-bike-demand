# Week 2 — Labs 3 and 4: team evidence

## Repository and starting point

Repository: https://github.com/Jeromsan/mlops-fri1-vanta-bike-demand.
Lab 4 branch: `lab4/prediction-api`, based on `main` at
`eca2b99` (Lab 2 merge). Lab 3 is already an ancestor of main through
`b8f7937`, PR #2. There is no local develop branch.

## Lab 3 recovered evidence and limits

The Dockerfile, locked uv installation, ignore rules and README are present.
The historical raw build log is `week-02-docker-build.log`. The historical
`week-02-container-tests.log` records **5 failed, 44 passed**. Keep this failure
visible: it is not a successful Lab 3 test run. That old image lacked Git error
handling and required project files; the current source already handles missing
Git and the Dockerfile copies the required preflight files. A new container test
run must verify the current revision independently. No new training run is
performed as part of Lab 4; the historical Lab 3 training/output evidence is
not reconstructed or invented.

The local trusted artifact is `artifacts/model.joblib`, with metadata alongside:

- model_version: `baseline-df42e666d6d6`
- SHA-256: `fd98ceafc57a5babce61ce703cbf9cb8d1f83c6820b0b34fe30ad1a0fc49c304`
- model run: `f185f6791a2f45d38abd320432dea414`
- training commit: `3b00e6018ac416a1d7d145fe85caa0270cccd231`
- training working tree dirty: **true**
- recorded validation MAE: RF `86.84685685591091`, mean `154.23179306864967`

The dirty training tree means the training commit alone does not identify all
training code. Do not call this a clean committed Lab 3 training artifact.
`lab4-saved-model-check.json` records a read-only integrity/evaluation check and
a real-model TestClient request. It must not be described as a Docker HTTP run.
Artifacts and MLflow outputs are ignored by Git; teammates must obtain this
exact trusted pair from the team. The distribution location remains to be
recorded by the artifact owner before handover.

## Lab 4 implementation and decision

Codex assisted with repository inspection, implementation, tests and evidence.
The service loads once during lifespan, verifies the artifact checksum and
feature order, reads the actual metadata version, and probes usability. Missing
or unusable models produce shared 503 readiness. No service training occurs.

Decision: reject every extra JSON field and all implicit numeric string/boolean
coercions. Keep the training predictor order and use already normalised weather
directly. The artifact is mounted read-only, so rebuilding the service does not
silently retrain or replace it. Synthetic unit-test artifacts are explicitly
labelled and are not course models or evaluation results.

## Verification record

Local API-only run: 141 passed (one dependency deprecation warning).
Full local suite: **191 passed, 2 warnings in 31.81s**, see
`lab4-local-tests.log`. The saved-model check reproduced validation MAE
`86.84685685591091` exactly and returned prediction `149.2911970908957` for the
saved request; see `lab4-saved-model-check.json`. Container verification and HTTP
evidence will be recorded after the image is built. No remote CI result is
claimed. Historical logs remain separate from new results.

Initial blocker: Docker engine unavailable, exact message:
`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.`
Docker Desktop subsequently became accessible; this does not by itself prove a
successful build, container test or HTTP request.

## Team review and handover — outstanding

Human reviews for Lab 4 have not occurred. Each member still needs a PR for
their real contribution and a review of another member, including a bad request
and no-model case. Do not merge or tag based on a claimed review by Codex.
Next owners: team members for scope allocation, reviewers for actual reviews,
integration owner for merging after checks and adding annotated `m2` plus its
link/release note. The personal repository location and actual individual
contributions must be supplied before writing the individual report on its main.
