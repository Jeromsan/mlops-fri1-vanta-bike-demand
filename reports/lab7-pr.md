# Lab 7 — Training Pipeline, Model Evaluation and Quality Gate

## Change and owner

Author: Merwane Kheloufi. Drafted with an AI assistant (Claude); read, run and
reviewed by the team before merge.

- `python -m bike_demand.pipeline run` is the single entry point: it checks the
  committed inputs, fits one candidate on 2011, writes it to
  `artifacts/candidates/<version>/`, scores the written bytes, the train mean
  and the incumbent named by `artifacts/accepted/CURRENT.json` on the same
  validation rows, applies `configs/gate-policy.yaml` and writes a decision
  record (`eligible` 0, `rejected` 2, `blocked` 3). It never writes under
  `artifacts/accepted/`.
- `adopt`, `promote` and `restore` are the only commands that change the
  accepted state. Promotion is manual, from reviewed `main`, and refuses a
  non-eligible or edited decision, an uncommitted decision, changed candidate
  bytes, a changed policy or a changed incumbent (compare-and-swap under a
  lock). The replaced version is kept and can be restored without retraining.
- Policy `gate-v1` was committed before any candidate existed. Its margins come
  from two committed measurements: seed-only variation of the accepted settings
  and serving memory.
- Three candidates, each committed with a written hypothesis before training.
- `scripts/cloud_run_release.py` serves each accepted version from an
  immutable bucket path through a tagged, no-traffic revision (dry run by
  default). `scripts/record.py` keeps raw command evidence.
- CI also runs `pipeline verify-records`, which recomputes every committed
  outcome from its recorded checks.
- `python -m bike_demand.train` and the API are unchanged.

## Evidence

Checked in a Linux workspace on the branch head:

- `ruff check`, `ruff format --check`: passed.
- `pytest -q`: 268 passed (206 existing + 62 new `lab7` tests), 2 deprecation
  warnings already present before this PR.
- The new tests run the real stages on a committed temporary Git project
  (a deterministic sample of the frozen CSV): an eligible decision that changes
  nothing; a rejection whose accepted files, pointer, history and
  `accepted_state_sha256` are byte-identical before and after; blocked runs
  for a missing incumbent, an uncommitted policy, settings out of bounds and
  an exhausted budget; refused promotions for each case listed above;
  promotion, then restore of the replaced version.
- One test failure during development was a real defect: a stale-decision
  promotion copied its bundle into `accepted/` before the compare-and-swap
  refused it. The check now happens first, under the same lock as the copy.
- End-to-end rehearsal in a separate clone on a stand-in incumbent trained with
  `python -m bike_demand.train` (validation MAE 86.84685685591091, equal to
  the recorded value; different bytes): adopt, three runs, `status`,
  `verify-records`, refused promotion of a rejected decision, then the API
  served `artifacts/accepted/<version>` and `scripts/smoke_api.py` passed all
  identity claims. Rehearsal outcomes are not team evidence; the official
  runs use the accepted bytes and are recorded in the team report.

Not run here: Docker build (Docker Hub was not reachable from the workspace)
and anything on Cloud Run or GCP.

Report: [Week 4 team report](week-04-team.md). Design and answers to the lab
questions: README, section "Pipeline and gate — Lab 7".

## Reviewer

Leave one actionable observation. Then challenge one claim you did not build
(suggestions in the team report), keep the raw output, and record the result.
Inspect CI for the latest pushed commit.
