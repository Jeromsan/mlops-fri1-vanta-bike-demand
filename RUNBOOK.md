# RUNBOOK: Bike Demand prediction service

For the operator on duty. Follow it top to bottom, and record each step with
`scripts/record.py` so the evidence stays raw. Commands are single lines
(PowerShell, macOS or Linux). Replace `<p>` (project), `<s>` (service) and
`<b>` (bucket); the region is `europe-west1`.

**Last verified context**

| Step | Last verified | Where | Evidence |
| --- | --- | --- | --- |
| Signals, diagnosis checks, rollback, recovery check | 2026-11-13, local rehearsal (one process per "revision", local stand-in bundle) | Laptop, no Cloud Run | [incident-local-drill.md](reports/lab8/incident-local-drill.md) |
| Cloud Run commands (sections 3–5) | **Not yet verified** on the team service | — | _to fill after the Cloud Run drill_ |
| Peer use of this runbook | **Not yet done** | — | _to fill: who followed it, what they had to ask_ |

## 1. Symptoms that bring you here

| Symptom | Signal (definitions in section 6) | Severity |
| --- | --- | --- |
| Answers name a version or SHA other than the accepted one | `identity_match` < 1.0 | Page |
| Known-valid predictions fail, time out or return 503 | `prediction_success` < 1.0 | Page |
| `/health` returns 503 | `readiness` < 1.0 | Page |
| Invalid requests are accepted (200) or crash (5xx) | `invalid_rejection` < 1.0 | Page |
| Successful predictions are much slower | p95 success latency > 2 × the baseline p95 on the same workload | Ticket; investigate, no rollback on this alone |
| Zero eligible attempts in the window | ratio is `null` ("no evidence") | Treat as **unknown**, never as healthy; check that the probe reaches the service |

These thresholds come from the workload. The probe sends a fixed, known-valid
cohort, so every failure in it is a regression, not noise. Latency on shared
machines varies, so it only opens a ticket. A short drill tests the alert path;
it does not establish long-term SLO compliance.

## 2. First checks (cheapest first, change nothing yet)

Save the raw output of each check before you interpret it.

1. **Measure.** Run the probe and compute the signals, using the retained
   expectation, never the service's own answer:
   `uv run --locked python scripts/probe.py <service URL> --period incident --out reports/lab8/<run>/probe-incident.jsonl`
   `uv run --locked python scripts/signals.py reports/lab8/<run>/probe-incident.jsonl --expected reports/lab8/<run>/expected.json --out reports/lab8/<run>/signals-incident.json`
2. **Service boundary: which revision gets traffic, and from which image?**
   `python scripts/cloud_run_release.py describe --project <p> --service <s>`
3. **Model boundary: what is loaded, and are the accepted bytes intact?**
   `curl <service URL>/health` gives `model_version`, `model_sha256` and `source_commit`.
   Compare them with `acceptance.json` of the accepted version, not with another endpoint of the same service.
   `uv run --locked python -m bike_demand.pipeline status`: `current_bytes_verified` and `previous_bytes_verified` must be `true`.
4. **Configuration boundary: the effective `MODEL_DIR` of each revision.**
   `gcloud run revisions describe <revision> --region europe-west1 --project <p> --format="value(spec.containers[0].env)"`
5. **Service events for the same window**, as the third source:
   `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=<s> AND jsonPayload.event:* AND timestamp>=\"<start UTC>\" AND timestamp<=\"<end UTC>\"" --project <p> --format=json > reports/lab8/<run>/events-incident.json`
   Then pass `--events` to `signals.py`. `model_unavailable` means the bundle failed to load.

## 3. Decide from the evidence

State at least two hypotheses, what each predicts and the check that tells
them apart. Keep the rejected ones in the incident record.

| Evidence | Likely cause | Action |
| --- | --- | --- |
| A new revision took traffic; its identity or `MODEL_DIR` differs from the accepted bundle; the accepted bytes are verified | Release or configuration regression | **Rollback** (section 4) |
| `model_unavailable` events and 503 on the new revision; the old revision is healthy | Bad bundle or bad mount on the new revision | **Rollback** (section 4) |
| Same identity as the baseline on every revision, failures grow with traffic | Capacity or saturation | No rollback: check Cloud Run instances, CPU and memory; escalate |
| Same identity, valid-input failures only for some inputs | Input or contract change upstream | No rollback: contain it (guard) and open a reviewed fix |
| `pipeline status` reports bytes not verified | Retained artifact altered | **Stop.** Do not load or relabel it; escalate (section 7) |

## 4. Safe action: roll back to a named, compatible target

A target is the revision that served an **accepted** bundle, not "whatever
was previous". Name it before switching.

1. Write the target down:
   - revision name;
   - `MODEL_DIR=/models/accepted/<version>`;
   - version and SHA-256 from `artifacts/accepted/<version>/acceptance.json`;
   - its gate decision in `reports/decisions/` (or the adoption record);
   - the image source commit.
2. Check compatibility:
   - the bundle's `model-metadata.json` lists the 12 features in contract order;
   - the revision's image was built from a reviewed commit with the same API contract;
   - `pipeline status` shows the bytes verified.

   A checksum mismatch **fails closed**: the API returns 503. Do not load
   or relabel that bundle.
3. Check the target before it gets users. On its tag URL (or through
   `gcloud run services proxy <s> --region europe-west1 --tag <tag> --port 8081`), run:
   `uv run --locked python scripts/smoke_api.py <tag URL> --expected-version <v> --expected-sha256 <sha> --expected-commit <commit>`
4. Make one controlled change:
   `python scripts/cloud_run_release.py traffic --project <p> --service <s> --revision <target revision> --execute`
5. If the accepted pointer itself must move back (rare: only when a promotion
   was wrong), run:
   `uv run --locked python -m bike_demand.pipeline restore --version <previous> --approved-by <name> --reason "<why>"`

**Never retrain as recovery.** A new training run creates a new version that
the gate must evaluate; that is not a rollback.

## 5. Verify recovery with fresh evidence

The `traffic` command succeeding, or an alert stopping, is not recovery.
Routing changes take a moment, so start the window after `describe` shows
100% on the target.

1. **Identity.** Run `smoke_api.py` against the **service** URL with the
   retained expectation; every claim must be ok.
2. **Behavior.** Run the same probe and seed for `--period recovery`. Expect
   `identity_match`, `prediction_success`, `readiness` and `invalid_rejection`
   at 1.0, and p95 near the baseline.
3. **Signals.** Read the service events for the recovery window: only the target
   version, and no `model_unavailable`.

Report all three for the same declared window. Also compare baseline,
incident and recovery with `signals.py` output, using the same definitions.
Say what is still unknown, for example predictive quality on live outcomes.

## 6. Signal definitions

Implemented in [`scripts/signals.py`](scripts/signals.py). For each signal the
ratio is good / eligible over one probe file, and the window runs from the
first to the last attempt time.

| Signal | Eligible | Good | Missing data |
| --- | --- | --- | --- |
| `prediction_success` | Known-valid `/predict` attempts from validation rows (Jan–Jun 2012), **including timeouts and refused connections** | 200, finite prediction ≥ 0, nonempty `model_version` | 0 eligible means `null`, "no evidence" |
| `invalid_rejection` | Deliberate contract violations (out-of-range, label as input, missing field, wrong type) | Any 4xx; a 200 or a 5xx is bad | same |
| `readiness` | `/health` probes | 200 | same |
| `identity_match` | 200 answers that report an identity | Version (and `/health` SHA) equal to the retained `acceptance.json` record | same |
| Latency | Successful and failed known-valid attempts, reported **separately** | p50/p95 nearest-rank in ms, with n | n = 0 means `null` |
| Replay quality | Successful known-valid predictions | MAE against `cnt` of the same validation rows, with coverage | Refuses held-test rows (Jul–Dec 2012) |

Invalid requests never enter `prediction_success`. A correct 422 is shown in
`invalid_rejection`, and a known-valid request rejected by a regression is a
failure.

## 7. Escalation

| When | To | With |
| --- | --- | --- |
| Accepted bytes not verified, or no compatible retained target | Team lead (_to fill_) and the member who holds `artifacts/` (_to fill_) | `pipeline status` output, the bucket path, decision records |
| Rollback done but the recovery checks still fail | Team lead (_to fill_) | All three sources for the window |
| Cloud Run access or quota blocks the action | Instructor | The exact error message; drill locally meanwhile |

## 8. Limits

- Service health is not predictive quality: the replay MAE uses validation
  rows, not live outcomes, and no held-test metric is computed before v1.0.0.
- The probe sees only its own traffic. Real clients' inputs are visible only in
  the service events.
- A rollback does not repair an upstream fault or a changed world.
- These steps are verified locally only until the Cloud Run row of the table
  above is filled.
