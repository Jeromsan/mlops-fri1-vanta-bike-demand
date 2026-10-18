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
