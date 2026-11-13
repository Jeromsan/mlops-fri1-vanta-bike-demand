# Lab 8 incident record: local rehearsal, 2026-11-13

**Scope: local rehearsal, not the Cloud Run drill.** It ran on one laptop
without `gcloud` or Docker. It tests the monitoring loop, the diagnosis checks
and the rollback procedure of [`RUNBOOK.md`](../../RUNBOOK.md) before the team
drills on its own Cloud Run service. Every number below comes from the raw files
in [`local-drill/`](local-drill/). None of them are expected values.

| Item | Value |
| --- | --- |
| Roles | One person ran all three roles (injector, operator, recorder). The operator therefore **knew the fault**, so this record shows that the signals and checks work. It does not show a blind diagnosis. The Cloud Run drill must rotate the roles. |
| Service | `bike_demand.api` under uvicorn on `127.0.0.1:8801`, code at commit `9d0c7ef` (the API is unchanged on this branch). A "release" is one process with its own `MODEL_DIR`. It stands in for a Cloud Run revision. |
| Accepted bundle | `baseline-9af131d45703`, SHA-256 `d24c050e…8b07`, adopted into a local drill store. **This is a local stand-in, not the team's `baseline-df42e666d6d6`**: that file is on another machine (see Blockers). |
| Independent expectation | [`expected.json`](local-drill/expected.json), copied from the bundle's `acceptance.json` before the drill. It is not taken from the service. |
| Workload | [`scripts/probe.py`](../../scripts/probe.py), seed 8: 60 known-valid `/predict` from validation rows (Jan–Jun 2012, features only), 12 deliberate invalid requests (6 rule violations), 12 `/health` probes. They are interleaved and replayed identically in all three periods. |
| Signals | [`scripts/signals.py`](../../scripts/signals.py). The definitions are in the RUNBOOK and are the same for all three periods. |

## Timeline (UTC)

| Time | Role | Observation or action | Raw evidence |
| --- | --- | --- | --- |
| 09:14:01 | operator | Release A ready, serves `baseline-9af131d45703` | [`events-baseline.log`](local-drill/events-baseline.log) |
| 09:14:07–09:14:12 | recorder | Baseline window, 84 attempts | [`probe-baseline.jsonl`](local-drill/probe-baseline.jsonl), [`signals-baseline.json`](local-drill/signals-baseline.json) |
| 09:14:24 | injector | Fault injected (sealed until the diagnosis below) | [`injector-sealed.json`](local-drill/injector-sealed.json) |
| 09:14:32.88 | operator | **First signal**: the first known-valid request answers 200 but reports `model_version` `rf-2b15ceb0c0e9` ≠ expected `baseline-9af131d45703` | `probe-incident.jsonl` line 1, request id `255da608…` |
| 09:14:32–09:14:38 | recorder | Incident window, 84 attempts | [`probe-incident.jsonl`](local-drill/probe-incident.jsonl), [`signals-incident.json`](local-drill/signals-incident.json) |
| 09:14:51 | operator | Check 1: `/health` identity | [`commands/03-health-identity.*`](local-drill/commands/) |
| 09:14:51 | operator | Check 2: retained accepted bytes (`pipeline status`) | `commands/04-retained-store-status.*` |
| 09:14:53 | operator | Check 3: effective configuration of the serving process | `commands/05-process-model-dir.*` |
| 09:15:05 | operator | Rollback target verified (checksum, feature schema) | `commands/06-rollback-target-check.*` |
| 09:15:07 | operator | Rollback: release B stopped, release A restarted on the retained bundle | [`rollback.json`](local-drill/rollback.json) |
| 09:15:09 | operator | Identity check against the retained expectation: all claims ok | `commands/07-smoke-identity.*` |
| 09:15:15–09:15:20 | recorder | Recovery window, 84 attempts | [`probe-recovery.jsonl`](local-drill/probe-recovery.jsonl), [`signals-recovery.json`](local-drill/signals-recovery.json) |

## First signal

Availability gave no signal. During the incident, `prediction_success` (60/60),
`readiness` (12/12) and `invalid_rejection` (12/12) all stayed at 1.0, so an
uptime or HTTP-200 check would have stayed green. What changed was:

- **`identity_match` 0/72** (baseline 72/72): every answer named a version
  other than the accepted one. This is the paging signal.
- **Successful-request latency p95 30.983 ms** (baseline 15.218 ms, n = 60
  each, nearest-rank). This is a supporting signal only, because laptop
  latency is noisy.

## Hypotheses

| | Predicted observation | Discriminating check | Actual result | Verdict |
| --- | --- | --- | --- | --- |
| **A. Release regression: the new release serves a bundle other than the accepted one** | `/health` and the service events name a different version and SHA; the effective `MODEL_DIR` is not the accepted path; the code commit is unchanged | Checks 1 and 3; compare `source_commit` | `/health` names `rf-2b15ceb0c0e9` / `2d7e97c5…`; `MODEL_DIR=…/candidates/rf-2b15ceb0c0e9`; `source_commit` unchanged `9d0c7ef`; the service events show only `rf-2b15ceb0c0e9` (60 × 2xx, 12 × 4xx) | **Supported** |
| B. More demand or host saturation slows the same model | Latency rises but the identity stays the same; failures or timeouts appear as load grows | Workload is fixed (same 84 attempts, same pause); compare identity | The workload was identical by construction, there were no failures and no timeouts, and the identity changed | **Contradicted** |
| C. The accepted bundle was altered in place | The version stays the same but the SHA-256 changes, and `pipeline status` reports bytes not verified | Check 2 | `current_bytes_verified: true`; the version itself differs | **Contradicted** |

`rf-2b15ceb0c0e9` is the Lab 7 candidate `c2-fully-grown-forest`. The gate
rejected it in the local Lab 7 run (gain 0.82 rentals/h < 1.0; file 222 MB
> 64 MiB). It had **never been accepted**. Its larger trees explain the slower
predictions.

**Fault revealed after the diagnosis** ([`injector-sealed.json`](local-drill/injector-sealed.json)):
release B was started with `MODEL_DIR` pointing at the candidate directory of
c2 instead of the accepted bundle. Because the operator knew this in advance,
the match between diagnosis and fault is expected here and proves little.

### Boundaries not checked

- Container image: there is no Docker on this machine, so no image digest.
- Upstream inputs from real clients: only the probe sent traffic.
- Cloud Run routing.

## Response

Rollback fits the evidence. The fault is a release selecting the wrong
artifact. The accepted bundle and the code are intact, so restoring the
retained release fully reverses it, with no retraining. A guard or a forward
fix would not remove the wrong model faster.

Rollback target, named before switching:

| Component | Value | Check |
| --- | --- | --- |
| Model | `baseline-9af131d45703`, SHA-256 `d24c050e3631d5b4c2feb8cb571bef6382d8c975c42a5c11edd28de78a0b8c07` | Recomputed by `shasum` = `acceptance.json` (`commands/06`), `current_bytes_verified: true` (`commands/04`) |
| Code and dependencies | Commit `9d0c7ef`, same `uv.lock` | Same commit that served the baseline |
| Feature schema | 12 features in contract order | Read from the bundle's `model-metadata.json` (`commands/06`) |
| Configuration | `MODEL_DIR` = the accepted bundle path | Same value as the baseline release |

## Three periods, same definitions

| | Baseline | Incident | After rollback |
| --- | --- | --- | --- |
| Window (UTC) | 09:14:07.03–09:14:12.26 | 09:14:32.88–09:14:38.69 | 09:15:15.62–09:15:20.90 |
| Served identity | `baseline-9af131d45703` (72) | `rf-2b15ceb0c0e9` (72) | `baseline-9af131d45703` (72) |
| `identity_match` | 72/72 | **0/72** | 72/72 |
| `prediction_success` | 60/60 | 60/60 | 60/60 |
| `invalid_rejection` | 12/12 | 12/12 | 12/12 |
| `readiness` | 12/12 | 12/12 | 12/12 |
| p50 / p95 success latency (ms, n = 60) | 10.761 / 15.218 | 20.463 / **30.983** | 11.688 / 14.963 |
| Replay MAE on the 60 validation rows (coverage 60/60) | 89.777 | 90.998 | 89.777 |
| Mean prediction | 139.217 | 137.721 | 139.217 |
| Service events, `/predict` | 60 × 2xx, 12 × 4xx | 60 × 2xx, 12 × 4xx | 61 × 2xx, 13 × 4xx (includes the smoke check's 1 valid and 1 invalid call) |

## Recovery claim and how the evidence agrees

The service again serves the accepted bundle `baseline-9af131d45703`. This
claim rests on three independent sources over 09:15:09–09:15:20:

1. **Identity.** `smoke_api.py` compared `/health` and `/predict` with the
   retained `acceptance.json` values; every claim was ok, exit 0.
2. **Behavior.** Fresh external requests from the same cohort: 60/60
   successful, 72/72 identity matches, p95 back to 14.963 ms.
3. **Signals.** The service's own events in the recovery window name only
   `baseline-9af131d45703`, with no `model_unavailable` events.

The replay MAE is identical to the baseline to the thousandth (89.777). The
same bytes on the same inputs give the same predictions, which supports the
claim that the exact accepted bundle is serving again.

What would falsify the claim:

- any recovery-window answer naming another version or SHA;
- a `/health` SHA that differs from `acceptance.json`;
- a replay MAE that differs from the baseline on the same cohort.

## What remains unknown

- **Predictive quality.** The replay MAE uses validation rows, not live outcomes,
  and service health says nothing about predictive quality. In this drill c2 was
  1.2 rentals/h worse on these 60 rows, a difference too small to detect from
  quality alone.
- **Observation window.** About 5 s per period with n = 60. This tests the alert
  and the recovery check; it says nothing about long-term SLO compliance.
- **Accepted bundle.** The local stand-in is not `baseline-df42e666d6d6`.
- **Not exercised here.** Cloud Run revisions, routing delay, image digest,
  memory: on a 512 MiB instance, c2's 222 MB file would probably also fail to
  load, a different signature.

## Detection gap and preventive actions

| Gap | Action | Owner | Verification |
| --- | --- | --- | --- |
| An uptime or 200-based check would have stayed green while a gate-rejected model served users | Page on `identity_match` < 1.0 against the retained record (RUNBOOK) | _to fill_ | The Cloud Run drill shows the page firing |
| Nothing stops a release from pointing `MODEL_DIR` outside `accepted/` | Forward fix to review: `cloud_run_release.py deploy` already builds the path from `CURRENT.json`; the API could refuse a bundle without `acceptance.json` | _to fill_ | A test that a candidate directory gives 503 |

## Blockers for the Cloud Run drill

| Blocker | Exact state | Next owner |
| --- | --- | --- |
| No `gcloud` and no Docker on this laptop | `command not found: gcloud`, `docker not found` | Member with Cloud Run access, on their machine |
| The team's accepted model `baseline-df42e666d6d6` is not on this laptop | `artifacts/` is out of Git; retraining gives other bytes and a random version | Member who holds `artifacts/` |
| Lab 7 is not yet merged on `main` | Branch `lab7/pipeline-gate` is ahead of `origin/main` | Reviewer of the Lab 7 PR |
| On this laptop, `.venv` `.pth` files are re-hidden by macOS within seconds (likely iCloud Desktop sync); `import bike_demand` then fails | Worked around with `PYTHONPATH=src` for every command | Merwane: move the repo out of iCloud Desktop |
