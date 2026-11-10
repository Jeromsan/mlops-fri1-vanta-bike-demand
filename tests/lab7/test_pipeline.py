"""End-to-end gate behavior on a committed temporary project.

Each test runs the real entry point stages: committed inputs, fit, written
candidate bytes, incumbent comparison, decision record and (separately)
promotion. A rejection must leave the accepted bytes and pointer unchanged.
"""

import json
import stat

import pytest
from conftest import REPO, SETTINGS, commit

from bike_demand import gate
from bike_demand.pipeline import (
    main,
    promote,
    restore,
    run_candidate,
    seed_variation,
    verify_records,
)
from bike_demand.store import Store, StoreError

pytestmark = pytest.mark.lab7


def run(project, candidate=None):
    return run_candidate(
        project.root,
        candidate or project.candidate,
        project.policy,
        project.store,
        project.decisions,
    )


def accepted_snapshot(project) -> dict:
    store = Store(project.store)
    return {
        "pointer": store.pointer.read_bytes(),
        "history": store.history.read_bytes(),
        "files": {
            path.relative_to(store.accepted).as_posix(): path.read_bytes()
            for path in sorted(store.accepted.rglob("*"))
            if path.is_file()
        },
    }


def test_eligible_candidate_is_decided_but_not_promoted(project):
    project.adopt(scale=3.0)  # a deliberately poor incumbent
    commit(project.root, "adopt incumbent")
    before = accepted_snapshot(project)
    record, path = run(project)
    assert record["outcome"] == "eligible", record["reasons"]
    assert record["exit_code"] == 0
    assert gate.verify_record(json.loads(path.read_text())) == []
    assert record["candidate"]["validation_mae"] < record["incumbent"]["validation_mae"]
    assert record["protocol"]["validation_rows"] == project.rows["validation"]
    assert (
        record["candidate"]["sha256_at_write"]
        == (record["candidate"]["identity"]["model_sha256"])
    )
    assert "test_mae" not in json.dumps(record)
    # Eligibility alone changes nothing: promotion is a separate decision.
    assert accepted_snapshot(project) == before


def test_rejection_preserves_the_accepted_state(project):
    project.adopt()
    project.write_policy(operation={"max_model_bytes": 1000})
    commit(project.root, "tight size rule")
    before = accepted_snapshot(project)
    digest = Store(project.store).status()["accepted_state_sha256"]
    record, path = run(project)
    assert record["outcome"] == "rejected"
    assert record["exit_code"] == 2
    assert Store(project.store).status()["accepted_state_sha256"] == digest
    assert record["reasons"][0].startswith("model_size: model file is")
    assert accepted_snapshot(project) == before
    # The rejected bytes stay outside accepted/ for review.
    assert (project.root / record["candidate"]["directory"]).is_dir()
    commit(project.root, "record rejection")
    with pytest.raises(StoreError, match="not eligible"):
        promote(
            project.root,
            path,
            project.policy,
            project.store,
            "Reviewer",
            project.promotions,
        )
    assert accepted_snapshot(project) == before


def test_missing_incumbent_blocks_instead_of_passing(project):
    record, _ = run(project)
    assert record["outcome"] == "blocked"
    statuses = {check["name"]: check["status"] for check in record["checks"]}
    assert statuses["incumbent_bytes"] == "fail"
    assert statuses["beats_incumbent"] == "not_run"
    assert record["candidate"]["evaluated"] is False


def test_uncommitted_policy_blocks_before_training(project):
    project.adopt()
    commit(project.root, "adopt")
    project.write_policy(quality={"min_gain_vs_naive": 0.5})  # edited, not committed
    record, _ = run(project)
    assert record["outcome"] == "blocked"
    assert "configs/gate-policy.yaml must be committed" in record["reasons"][0]
    assert not (project.store / "candidates").exists()


def test_settings_outside_policy_block(project):
    project.adopt()
    path = project.write_candidate("bad", {**SETTINGS, "n_estimators": 5000})
    commit(project.root, "out-of-range candidate")
    record, _ = run(project, path)
    assert record["outcome"] == "blocked"
    assert "n_estimators=5000 outside [1, 200]" in record["reasons"][0]


def test_budget_counts_only_evaluated_candidates(project):
    project.adopt(scale=3.0)
    project.write_policy(budget={"max_evaluated_candidates": 1})
    commit(project.root, "budget of one")
    assert run(project)[0]["outcome"] == "eligible"
    second, _ = run(project)
    assert second["outcome"] == "blocked"
    assert second["reasons"][0] == (
        "budget: integrity failed (1 candidate(s) already evaluated under this policy)"
    )


def test_promotion_is_manual_checked_and_keeps_the_previous_version(project):
    first = project.adopt(scale=3.0)
    commit(project.root, "adopt")
    record, path = run(project)
    assert record["outcome"] == "eligible"
    with pytest.raises(StoreError, match="must be committed"):
        promote(
            project.root, path, project.policy, project.store, "R", project.promotions
        )
    commit(project.root, "review decision")
    pointer, change = promote(
        project.root,
        path,
        project.policy,
        project.store,
        "Reviewer",
        project.promotions,
    )
    assert pointer["model_version"] == record["candidate"]["model_version"]
    assert pointer["previous"]["model_version"] == first["model_version"]
    store = Store(project.store)
    status = store.status()
    assert status["current_bytes_verified"] and status["previous_bytes_verified"]
    assert json.loads(change.read_text())["before"]["model_version"] == "incumbent-1"
    # Recovery without retraining: the replaced version is still served-ready.
    restored, _ = restore(
        project.store, "incumbent-1", "Reviewer", "drill", project.promotions
    )
    assert restored["model_version"] == "incumbent-1"
    assert len(store.history.read_text().splitlines()) == 3


def test_promotion_refuses_changed_bytes_policy_or_incumbent(project):
    project.adopt(scale=3.0)
    commit(project.root, "adopt")
    first, first_path = run(project)
    second, second_path = run(project)
    commit(project.root, "review decisions")
    args = (project.policy, project.store, "Reviewer", project.promotions)

    # 1. Bytes changed after evaluation.
    model = project.root / second["candidate"]["directory"] / "model.joblib"
    original = model.read_bytes()
    model.write_bytes(original + b"tampered")
    with pytest.raises(StoreError):
        promote(project.root, second_path, *args)
    model.write_bytes(original)

    # 2. Wrong branch.
    with pytest.raises(StoreError, match="promote from reviewed release"):
        promote(project.root, first_path, *args, branch="release")

    # 3. Incumbent changed after the second decision was made.
    promote(project.root, first_path, *args)
    before = accepted_snapshot(project)
    with pytest.raises(StoreError, match="accepted state changed"):
        promote(project.root, second_path, *args)
    assert accepted_snapshot(project) == before
    assert not (project.store / "accepted/.lock").exists()

    # 4. Policy edited after the decision.
    project.write_policy(quality={"min_gain_vs_naive": 2.0})
    commit(project.root, "new policy")
    with pytest.raises(StoreError, match="policy changed"):
        promote(project.root, first_path, *args)


def test_edited_decision_record_is_detected(project):
    project.adopt()
    project.write_policy(operation={"max_model_bytes": 1000})
    commit(project.root, "tight size rule")
    record, path = run(project)
    assert record["outcome"] == "rejected"
    edited = {**record, "outcome": "eligible", "exit_code": 0}
    path.write_text(json.dumps(edited))
    problems = verify_records(project.decisions)[path.as_posix()]
    assert any("recomputed 'rejected'" in item for item in problems)
    assert main(["verify-records"]) == 1


def test_cli_exit_codes_follow_the_outcome(project, capsys):
    project.adopt()
    project.write_policy(operation={"max_model_bytes": 1000})
    commit(project.root, "tight size rule")
    code = main(["run", "--candidate", str(project.candidate)])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "rejected"
    assert main(["status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["current"]["model_version"] == "incumbent-1"
    assert len(status["candidates"]) == 1


def test_adopt_runs_once_and_checks_the_expected_identity(project):
    directory, metadata = project.incumbent_bundle("other")
    code = main(
        [
            "adopt",
            "--from",
            str(directory),
            "--expected-version",
            "other",
            "--expected-sha256",
            "0" * 64,
            "--approved-by",
            "A",
            "--note",
            "wrong digest",
        ]
    )
    assert code == 1
    assert not (project.store / "accepted/CURRENT.json").exists()
    project.adopt()
    with pytest.raises(StoreError, match="already exists"):
        project.adopt()


def test_accepted_files_are_read_only_after_adoption(project):
    project.adopt()
    current = Store(project.store).version_dir("incumbent-1") / "model.joblib"
    assert stat.S_IMODE(current.stat().st_mode) == stat.S_IREAD


def test_seed_variation_changes_only_the_seed(project):
    result = seed_variation(project.root, REPO / "configs/baseline.yaml", [0, 1])
    assert set(result["validation_mae"]) == {"0", "1"}
    assert result["settings"]["random_state"] == 42  # the recorded accepted setting
    assert result["range"] == result["max"] - result["min"]
    assert result["validation_rows"] == project.rows["validation"]


def test_usage_errors_never_look_like_a_rejection(project, capsys):
    assert main(["run"]) == 1  # missing --candidate; argparse alone would exit 2
    assert main(["--help"]) == 0
