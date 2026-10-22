# Lab 5 — Verify the Deployed Model and Log Requests

## Changes

I implemented the Lab 5 changes to verify deployment identity and add structured request logging.

I extended `/health` to expose the model version, the SHA-256 hash of the loaded model bytes, and the source commit, while preserving existing fields and behavior. I added JSON request events without logging request contents, together with an external HTTP checker that compares independently supplied expected values and fails on any mismatch.

I updated the Docker configuration to preserve locked dependencies, use a read-only model mount, and disable Uvicorn access logs. Team reports are no longer copied into the image.

I also documented PowerShell deployment commands, the ten required decisions, deliberate failure scenarios, and cleanup in the README. No model was retrained or replaced.

## Verification

I verified all the following points:

- Ruff, formatting checks, and preflight passed.
- All 205 tests passed locally and all 205 passed inside the image without external network access. Each suite reported two deprecation warnings.
- Against the running container: deployment identities matched, valid prediction returned HTTP 200, invalid input returned HTTP 422, and the external checker exited with code 0.
- With an incorrect expected commit: the checker exited with code 1 even though the service returned HTTP 200.
- With the same image and no model: responses were 503/503/422, and the normal deployment checker exited with code 1.
- Application log lines were valid JSON, and each saved response's request identifier appeared exactly once in the request events.
- `/models` was mounted read-only, and ports were published only on `127.0.0.1`.

Source commit used for the build:
`baee60a4dd24b4a30deb84320b6b4bc33c0e4def`

Image ID:
`sha256:02615bba3ec726d316b2e73863da6bf8e52dd03a6ea74c5ed29a9ae7f7d30f65`

The evidence files and report were added after this commit.

Report: [Week 3 team report](reports/week-03-team.md).

Evidence: [Lab 5 execution records](reports/lab5-20261022/), including:

- [Successful deployment check](reports/lab5-20261022/check.log)
- [Incorrect expected revision](reports/lab5-20261022/wrong-commit.log)
- [Container logs without a model](reports/lab5-20261022/missing-container.log)
- [Tests inside the image](reports/lab5-20261022/container-tests.log)

## Limitations and Requested Review

I completed the local and Docker checks described above. No remote CI execution or approval from another team member is claimed.

The inherited model was trained from a modified working tree, this provenance limitation is documented. 

For review, follow only the README's “Deploy — Lab 5” section on this branch. Change the host port, for example from 8000 to 8010, then verify the responses, deployment identities, logs, and corresponding evidence. Also verify the read-only mount, invalid-input behavior, and missing-model behavior.

Leave a concrete review observation. I will document my response and any subsequent verification.

Merge only after this review and successful checks.