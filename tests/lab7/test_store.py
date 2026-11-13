"""Accepted-state boundary: immutable versions, compare-and-swap pointer, lock."""

import hashlib
import json
import stat

import pytest

from bike_demand.store import Store, StoreError, bundle_identity

pytestmark = pytest.mark.lab7


def bundle(path, version="v1", payload=b"model-bytes"):
    path.mkdir(parents=True)
    (path / "model.joblib").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (path / "model-metadata.json").write_text(
        json.dumps({"model_version": version, "model_sha256": digest})
    )
    return path


def test_metadata_must_match_bytes(tmp_path):
    source = bundle(tmp_path / "b")
    (source / "model.joblib").write_bytes(b"other")
    with pytest.raises(StoreError, match="differ from metadata"):
        bundle_identity(source)


def test_install_is_read_only_and_idempotent(tmp_path):
    store = Store(tmp_path / "store")
    source = bundle(tmp_path / "b")
    first = store.install(source, {"approved_by": "A"})
    again = store.install(source, {"approved_by": "A"})
    assert first["model_sha256"] == again["model_sha256"]
    installed = store.version_dir("v1")
    for name in ("model.joblib", "model-metadata.json", "acceptance.json"):
        assert stat.S_IMODE((installed / name).stat().st_mode) == stat.S_IREAD
    assert not list(store.accepted.glob(".partial-*"))


def test_same_version_with_other_bytes_is_refused(tmp_path):
    store = Store(tmp_path / "store")
    store.install(bundle(tmp_path / "a"), {})
    with pytest.raises(StoreError, match="retained bytes differ"):
        store.install(bundle(tmp_path / "b", payload=b"different"), {})


def test_switch_is_compare_and_swap(tmp_path):
    store = Store(tmp_path / "store")
    v1 = store.install(bundle(tmp_path / "a", "v1", b"one"), {})
    v2 = store.install(bundle(tmp_path / "b", "v2", b"two"), {})
    store.switch(v1, expected_current=None, change={"action": "adopt"})
    before = store.pointer.read_bytes()
    with pytest.raises(StoreError, match="accepted state changed"):
        store.switch(v2, expected_current=None, change={"action": "promote"})
    assert store.pointer.read_bytes() == before
    pointer = store.switch(v2, expected_current=v1, change={"action": "promote"})
    assert pointer["previous"] == {
        "model_version": "v1",
        "model_sha256": v1["model_sha256"],
    }
    assert len(store.history.read_text().splitlines()) == 2


def test_held_lock_blocks_pointer_change(tmp_path):
    store = Store(tmp_path / "store")
    v1 = store.install(bundle(tmp_path / "a"), {})
    store.lock_path.write_text("held by another promotion")
    with pytest.raises(StoreError, match="lock"):
        store.switch(v1, expected_current=None, change={})
    assert not store.pointer.exists()


def test_interrupted_install_is_ignored_and_cleaned(tmp_path):
    store = Store(tmp_path / "store")
    partial = store.accepted / ".partial-v1"
    partial.mkdir(parents=True)
    (partial / "model.joblib").write_bytes(b"half written")
    assert store.status()["partial_outputs"] == ["accepted/.partial-v1"]
    assert store.status()["accepted_versions"] == []
    store.install(bundle(tmp_path / "a"), {})
    assert store.status()["partial_outputs"] == []


def test_status_detects_changed_retained_bytes(tmp_path):
    store = Store(tmp_path / "store")
    v1 = store.install(bundle(tmp_path / "a"), {})
    store.switch(v1, expected_current=None, change={})
    model = store.version_dir("v1") / "model.joblib"
    model.chmod(stat.S_IWRITE | stat.S_IREAD)
    model.write_bytes(b"silently replaced")
    status = store.status()
    assert status["current_bytes_verified"] is False
    with pytest.raises(StoreError):
        store.resolve_current()


@pytest.mark.parametrize("name", ["", "../x", ".partial-v1", "a/b"])
def test_version_names_cannot_escape_the_store(tmp_path, name):
    with pytest.raises(StoreError, match="invalid version"):
        Store(tmp_path).version_dir(name)
