"""Dry-run command construction for the Cloud Run release helper (no gcloud)."""

import hashlib
import json
import runpy
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bike_demand.store import Store

pytestmark = pytest.mark.lab7
SCRIPT = runpy.run_path(str(Path(__file__).parents[2] / "scripts/cloud_run_release.py"))
BASE = ["--project", "p", "--service", "bike-demand"]


@pytest.fixture
def store(tmp_path):
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "model.joblib").write_bytes(b"accepted bytes")
    digest = hashlib.sha256(b"accepted bytes").hexdigest()
    (source / "model-metadata.json").write_text(
        json.dumps({"model_version": "baseline-df42e666d6d6", "model_sha256": digest})
    )
    root = tmp_path / "artifacts"
    Store(root).accept(source, {}, expected_current=None, change={"action": "adopt"})
    return root


def planned(capsys, *args):
    assert SCRIPT["main"]([*args]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    return [line["command"][1:] for line in lines if "command" in line], lines


def test_deploy_creates_a_tagged_revision_without_traffic(store, capsys):
    commands, lines = planned(
        capsys, "deploy", *BASE, "--store", str(store), "--image", "img:abc"
    )
    (command,) = commands
    assert command[:3] == ["run", "deploy", "bike-demand"]
    assert "--no-traffic" in command
    assert command[command.index("--tag") + 1] == "v-baseline-df42e666d6d6"
    env = command[command.index("--update-env-vars") + 1]
    assert env == "MODEL_DIR=/models/accepted/baseline-df42e666d6d6"
    assert lines[-1]["expected_sha256"] == hashlib.sha256(b"accepted bytes").hexdigest()
    assert all(line.get("execute") is False for line in lines if "command" in line)


def test_upload_never_overwrites_a_version_path(store, capsys):
    commands, _ = planned(
        capsys, "upload", *BASE, "--store", str(store), "--bucket", "b"
    )
    assert [command[-1] for command in commands] == [
        f"gs://b/accepted/baseline-df42e666d6d6/{name}"
        for name in ("model.joblib", "model-metadata.json", "acceptance.json")
    ]
    assert all("--no-clobber" in command for command in commands)


def test_changed_local_bytes_stop_the_release(store):
    model = store / "accepted/baseline-df42e666d6d6/model.joblib"
    model.chmod(stat.S_IWRITE | stat.S_IREAD)
    model.write_bytes(b"changed")
    with pytest.raises(SystemExit, match="differ from acceptance"):
        SCRIPT["main"](["deploy", *BASE, "--store", str(store), "--image", "i"])


def test_traffic_and_setup_commands(capsys):
    commands, _ = planned(capsys, "traffic", *BASE, "--revision", "bike-demand-x")
    assert commands[0][-2:] == ["--to-revisions", "bike-demand-x=100"]
    commands, _ = planned(capsys, "setup", *BASE, "--bucket", "b")
    assert "name=models,type=cloud-storage,bucket=b,readonly=true" in commands[0]
    with pytest.raises(SystemExit):
        SCRIPT["main"](["traffic", *BASE])


def test_revision_names_fit_cloud_run_limits():
    suffix = SCRIPT["suffix_for"](
        "rf-" + "a" * 80, "bike-demand-service", datetime(2026, 11, 10, tzinfo=UTC)
    )
    assert len("bike-demand-service-" + suffix) <= 63
    assert suffix.endswith("-11100000")
    assert SCRIPT["tag_for"]("2026_Model") == "v-2026-model"
