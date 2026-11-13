# Week 4 — Lab 7

Training pipeline, model evaluation and quality gate. The design and the
answers to the lab questions are in the README section
[Pipeline and gate — Lab 7](../README.md#pipeline-and-gate--lab-7). This report
records who did what, the order of the evidence and the results we actually
observed. Cells marked _to fill_ are filled from the raw files of the official
run; nothing here is copied from a rehearsal.

## Shared contract

| Item | Agreement |
| --- | --- |
| Inputs | A committed candidate config in `configs/candidates/`, the frozen snapshot (`data/manifest.json`), and the incumbent named by `artifacts/accepted/CURRENT.json`. |
| Policy | `configs/gate-policy.yaml`, version `gate-v1`, committed before any candidate config existed. A rule change needs a new version, a PR and a written reason. |
| Outcomes | `eligible` (0), `rejected` (2), `blocked` (3); 1 means the run crashed before deciding. Only `eligible` can be promoted, manually, from reviewed `main`. |
| Evidence | Decision records in `reports/decisions/`, pointer changes in `reports/promotions/`, raw command output in `reports/lab7-run/`. At most three screenshots. |

## Who did what

| Member | Own change (PR) | Review / challenge of another member's work |
| --- | --- | --- |
| Merwane Kheloufi | Pipeline entry point, gate rules, accepted store, policy `gate-v1`, three candidates, Cloud Run release helper, README section (PR _to fill_) | _to fill_ |
| _to fill_ | Adoption of the accepted model and the official candidate runs on the machine that holds it | _to fill_ |
| _to fill_ | Cloud Run setup, upload and revision check | Independent challenge (below) |

Assistance: the code, tests and documentation of the first PR were drafted
with an AI assistant (Claude) and then read, run and reviewed by the team.

## Order of the evidence

The policy must not be chosen to fit a result. `git log --reverse --format="%h %cI %s" -- configs/ reports/decisions/`
shows the order below; the decision records also store the policy SHA-256 and
the commit they ran on.

1. Pipeline, gate and store code with tests (no policy yet).
2. `gate-v1` policy with the two measurements that size it.
3. The three candidate configs, each with a written hypothesis.
4. Decision records, one per run (_to fill_: commit link).

### Measurements behind the thresholds (before any candidate)

| Measurement | Result | Raw record |
| --- | --- | --- |
| Validation MAE of the accepted settings, ten seeds, only `random_state` changed | 86.42 to 87.11 rentals/h (range 0.69, std 0.19) | [seed-variation.json](lab7/seed-variation.json) |
| Serving process memory after loading a 5.2 MB model with the accepted settings | 218 MiB RSS (Linux, locked dependencies) | [serving-memory.json](lab7/serving-memory.json) |
| Validation error of a stand-in with the accepted settings (same MAE as the recorded 86.8469; not our bytes) | Working-day peak hours: 17% of rows, 40% of absolute error. Mean signed error −82 rentals/h | [error-analysis-standin.json](lab7/error-analysis-standin.json) |

_To fill_: rerun `scripts/error_analysis.py` on
`artifacts/accepted/baseline-df42e666d6d6` and link the output here.

## Official run procedure

Run from a clean checkout of reviewed `main` on the machine that holds the
accepted model. Each command is wrapped with `scripts/record.py`, which keeps
the command, its UTC times, its exit code and its unedited output:

```bash
uv run --locked python scripts/record.py reports/lab7-run 01-adopt -- uv run --locked python -m bike_demand.pipeline adopt --from artifacts --expected-version baseline-df42e666d6d6 --expected-sha256 fd98ceafc57a5babce61ce703cbf9cb8d1f83c6820b0b34fe30ad1a0fc49c304 --approved-by "<name>" --note "Approved Lab 4/5 artifact; trained from a dirty tree"
uv run --locked python scripts/record.py reports/lab7-run 02-status-before -- uv run --locked python -m bike_demand.pipeline status
uv run --locked python scripts/record.py reports/lab7-run 03-run-c1 -- uv run --locked python -m bike_demand.pipeline run --candidate configs/candidates/c1-deeper-trees.yaml
uv run --locked python scripts/record.py reports/lab7-run 04-status-after-c1 -- uv run --locked python -m bike_demand.pipeline status
uv run --locked python scripts/record.py reports/lab7-run 05-run-c2 -- uv run --locked python -m bike_demand.pipeline run --candidate configs/candidates/c2-fully-grown-forest.yaml
uv run --locked python scripts/record.py reports/lab7-run 06-run-c3 -- uv run --locked python -m bike_demand.pipeline run --candidate configs/candidates/c3-small-forest.yaml
uv run --locked python scripts/record.py reports/lab7-run 07-status-after -- uv run --locked python -m bike_demand.pipeline status
uv run --locked python scripts/record.py reports/lab7-run 08-verify-records -- uv run --locked python -m bike_demand.pipeline verify-records
```

Around a rejected run, also check the live service before and after with
`scripts/smoke_api.py` against the Cloud Run URL (files `02b-` and `04b-`).

## Decisions

From `reports/decisions/` (one row per run, in order):

| Candidate | Decision record | Outcome | Candidate MAE | Incumbent MAE | Train-mean MAE | Model bytes | p95 ms | Rules that failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| c1-deeper-trees | _to fill_ | _to fill_ | | | | | | |
| c2-fully-grown-forest | _to fill_ | _to fill_ | | | | | | |
| c3-small-forest | _to fill_ | _to fill_ | | | | | | |

For each hypothesis, one sentence on whether the observation supports it:
_to fill_.

## A rejection preserves the accepted state

| | Before (`02-status-before`) | After (`04-status-after-c1`) |
| --- | --- | --- |
| `CURRENT` version | _to fill_ | _to fill_ |
| `CURRENT` model SHA-256 | _to fill_ | _to fill_ |
| `accepted_state_sha256` | _to fill_ | _to fill_ |
| Version served by Cloud Run (`/health`) | _to fill_ | _to fill_ |
| Decision records | _to fill_ | _to fill_ |

The decision log changes; the accepted bundle and the served version do not.

## Promotion, or why nothing was promoted

_To fill with what actually happened, one of:_

- **Eligible candidate promoted:** decision record, approval by a member who
  did not run it, `reports/promotions/` record, previous version kept
  (`previous_bytes_verified: true`), new revision name, identity check on its
  tag URL, traffic switch, previous revision still listed.
- **Nothing qualified:** we kept `baseline-df42e666d6d6`. Name the measured
  rules that failed. An accepted equivalent would not show improved accuracy,
  so we did not force a pass. State what Lab 8 receives instead.

## Cloud Run

| Item | Value |
| --- | --- |
| Service, region | _to fill_ |
| Image and its source commit | _to fill_ |
| Bucket path of the accepted bundle and the read-back SHA-256 check | _to fill_ |
| Revision serving the accepted version | _to fill_ |
| Previous revision still available | _to fill_ |
| Identity check output (`smoke_api.py`) | _to fill_ |

## Independent challenge

The reviewer did not write the pipeline. They choose one claim, predict how
it should fail, run it on their own trusted artifacts and keep the raw output.
Suggested claims:

1. Edit a committed decision's `outcome` to `eligible`: `verify-records`
   and `promote` must refuse it, and CI must fail on the PR.
2. Change one byte of a rejected or eligible candidate after its decision:
   `promote` must refuse it.
3. Edit the policy without committing it, then run a candidate: the run must
   be `blocked` before training and the budget must not move.
4. Promote an old eligible decision after `CURRENT` changed: compare-and-swap
   must refuse it and `accepted_state_sha256` must not move.

| Reviewer | Claim challenged | Prediction | Observed (raw file) | Gap found and repair |
| --- | --- | --- | --- | --- |
| _to fill_ | | | | |

A green result without the intended check running is a gap, not a pass.

## Observations and limitations

- The accepted model came from a dirty working tree (Lab 4 record). We adopted
  it unchanged and kept that limitation; the gate requires clean source for
  every new candidate.
- Latency is a warm in-process measurement on the evaluating machine, not a
  Cloud Run SLO.
- One validation window; the held test stays unscored until v1.0.0.
- While writing the tests, a stale-decision promotion copied its bundle into
  `accepted/` before the compare-and-swap refused it. The pointer was safe but
  `accepted/` changed. We moved the incumbent check before the copy and run
  both under the same lock; the test now checks that `accepted/` is unchanged.

## Lab 8 — Monitoring, incident and rollback

Design and procedure: README section
[Monitoring, incident and rollback — Lab 8](../README.md#monitoring-incident-and-rollback--lab-8)
and [`RUNBOOK.md`](../RUNBOOK.md). This section links the Lab 7 retained
versions to the Lab 8 evidence. As in Lab 7, cells marked _to fill_ come from
raw files of the official run.

### Roles (rotated, agreed before the drill)

| Drill | Injector | Operator (does not know the fault) | Recorder |
| --- | --- | --- | --- |
| Local rehearsal, 2026-11-13 | Merwane Kheloufi, with an AI assistant | same person, so **not blind** | same person |
| Cloud Run drill | _to fill_ | _to fill_ | _to fill_ |

### From Lab 7 to Lab 8

| Item | Local rehearsal | Cloud Run drill |
| --- | --- | --- |
| Accepted bundle served (rollback target) | `baseline-9af131d45703`, local stand-in | `baseline-df42e666d6d6` (_to fill_: revision) |
| Integrity record | `acceptance.json` → [`expected.json`](lab8/local-drill/expected.json) | _to fill_ |
| Gate decision behind it | Local adoption; all 3 local candidates rejected | _to fill_: link to `reports/decisions/` |
| Fault (revealed after diagnosis) | Release served gate-rejected candidate c2 (`rf-2b15ceb0c0e9`) | _to fill_ |

### Results

Local rehearsal (full record: [`incident-local-drill.md`](lab8/incident-local-drill.md)):

| | Baseline | Incident | After rollback |
| --- | --- | --- | --- |
| Served identity | `baseline-9af131d45703` | `rf-2b15ceb0c0e9` | `baseline-9af131d45703` |
| `identity_match` | 72/72 | **0/72** | 72/72 |
| `prediction_success` | 60/60 | 60/60 | 60/60 |
| p95 success latency (ms, n = 60) | 15.218 | 30.983 | 14.963 |
| Replay MAE, validation rows | 89.777 | 90.998 | 89.777 |

The first signal was the identity mismatch. All availability signals stayed
at 1.0 during the incident, so a 200-based check would have missed it.

Cloud Run drill: _to fill_ with the same table from `signals.py` output.

### Peer use of the runbook

| Reviewer (did not write it) | What they could do alone | Where they had to ask | Revision made |
| --- | --- | --- | --- |
| _to fill_ | | | |

### Limitations

- The local rehearsal had one person in all roles; the diagnosis was not blind.
- About 5 s windows with n = 60: enough to test the alert and the recovery
  check, not to claim an SLO.
- Service health is separate from predictive quality; the replay MAE uses
  validation rows, and the held test stays unscored.
