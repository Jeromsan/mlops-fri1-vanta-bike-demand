"""Accepted-model store: immutable versions, one moving pointer, kept history.

Layout under the store root (``artifacts/`` by default, ignored by Git)::

    candidates/<version>/          written only by the pipeline; never served
    candidates/.partial-<version>/ incomplete output; never evaluated or promoted
    accepted/<version>/            immutable bundle: model, metadata, acceptance
    accepted/.partial-<version>/   interrupted install; ignored, safe to delete
    accepted/CURRENT.json          the single pointer to the accepted version
    accepted/history.jsonl         append-only record of every pointer change
    accepted/.lock                 held during a pointer change

Candidates can never write under ``accepted/``. Promotion copies verified bytes
into a new version directory and then replaces the pointer atomically. A
rejected candidate therefore cannot change the accepted state.
"""

import json
import os
import shutil
import stat
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from bike_demand.preflight import sha256

BUNDLE_FILES = ("model.joblib", "model-metadata.json")


class StoreError(RuntimeError):
    """The accepted state cannot be read or changed safely."""


def now() -> str:
    return datetime.now(UTC).isoformat()


def remove_tree(path: Path) -> None:
    """Delete an abandoned partial directory, including read-only files."""

    def make_writable(function, target, _error):
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        function(target)

    shutil.rmtree(path, onexc=make_writable)


def write_json_atomic(path: Path, value: dict) -> None:
    """Write next to the target, then replace it in one rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def bundle_identity(directory: Path) -> dict:
    """Identify a bundle by its exact bytes; metadata must agree with them."""
    for name in BUNDLE_FILES:
        if not (directory / name).is_file():
            raise StoreError(f"{directory.name}: missing {name}")
    metadata = json.loads((directory / "model-metadata.json").read_text())
    digest = sha256(directory / "model.joblib")
    if metadata.get("model_sha256") != digest:
        raise StoreError(f"{directory.name}: model bytes differ from metadata")
    version = metadata.get("model_version")
    if not isinstance(version, str) or not version:
        raise StoreError(f"{directory.name}: metadata has no model_version")
    return {
        "model_version": version,
        "model_sha256": digest,
        "metadata_sha256": sha256(directory / "model-metadata.json"),
        "model_bytes": (directory / "model.joblib").stat().st_size,
    }


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.candidates = self.root / "candidates"
        self.accepted = self.root / "accepted"
        self.pointer = self.accepted / "CURRENT.json"
        self.history = self.accepted / "history.jsonl"
        self.lock_path = self.accepted / ".lock"

    # ---- candidates -------------------------------------------------------
    def candidate_staging(self, version: str) -> Path:
        staging = self.candidates / f".partial-{version}"
        if staging.exists() or (self.candidates / version).exists():
            raise StoreError(f"candidate {version} already exists")
        staging.mkdir(parents=True)
        return staging

    def complete_candidate(self, staging: Path, version: str) -> Path:
        final = self.candidates / version
        staging.rename(final)
        return final

    def candidate_dir(self, version: str) -> Path:
        return self.candidates / version

    # ---- accepted state ---------------------------------------------------
    def read_current(self) -> dict | None:
        if not self.pointer.exists():
            return None
        return json.loads(self.pointer.read_text())

    def version_dir(self, version: str) -> Path:
        if not version or "/" in version or "\\" in version or version.startswith("."):
            raise StoreError(f"invalid version name: {version!r}")
        return self.accepted / version

    def verify_version(self, version: str, expected_sha256: str) -> dict:
        directory = self.version_dir(version)
        identity = bundle_identity(directory)
        if identity["model_version"] != version:
            raise StoreError(f"{version}: metadata names {identity['model_version']}")
        if identity["model_sha256"] != expected_sha256:
            raise StoreError(f"{version}: retained bytes differ from the record")
        return identity

    def resolve_current(self) -> tuple[dict, Path]:
        """Return the pointer and its verified bundle, or raise."""
        pointer = self.read_current()
        if pointer is None:
            raise StoreError("no accepted version: run `pipeline adopt` first")
        self.verify_version(pointer["model_version"], pointer["model_sha256"])
        return pointer, self.version_dir(pointer["model_version"])

    @contextmanager
    def locked(self):
        self.accepted.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
        except FileExistsError as error:
            raise StoreError(
                "another pointer change holds accepted/.lock; inspect it before "
                "removing it by hand"
            ) from error
        try:
            os.write(descriptor, f"pid={os.getpid()} at={now()}\n".encode())
            os.close(descriptor)
            yield
        finally:
            self.lock_path.unlink(missing_ok=True)

    def install(self, source: Path, acceptance: dict) -> dict:
        """Copy a verified bundle into accepted/<version>; idempotent on retry."""
        identity = bundle_identity(source)
        version = identity["model_version"]
        final = self.version_dir(version)
        if final.exists():
            # A retry after an interrupted promotion: reuse only identical bytes.
            return self.verify_version(version, identity["model_sha256"])
        staging = self.accepted / f".partial-{version}"
        if staging.exists():
            remove_tree(staging)
        staging.mkdir(parents=True)
        for name in BUNDLE_FILES:
            shutil.copy2(source / name, staging / name)
        installed = bundle_identity(staging)
        if installed["model_sha256"] != identity["model_sha256"]:
            raise StoreError(f"{version}: copy changed the model bytes")
        (staging / "acceptance.json").write_text(
            json.dumps({**acceptance, **installed}, indent=2, allow_nan=False) + "\n"
        )
        for name in (*BUNDLE_FILES, "acceptance.json"):
            # Read-only files make accidental in-place edits fail loudly.
            os.chmod(staging / name, stat.S_IREAD)
        staging.rename(final)
        return installed

    def _expect(self, expected_current: dict | None) -> dict | None:
        """Compare-and-swap guard: the incumbent must be the one evaluated."""
        current = self.read_current()
        observed = (
            None
            if current is None
            else (current["model_version"], current["model_sha256"])
        )
        expected = (
            None
            if expected_current is None
            else (expected_current["model_version"], expected_current["model_sha256"])
        )
        if observed != expected:
            raise StoreError(
                f"accepted state changed: expected {expected}, found {observed}; "
                "re-evaluate against the new incumbent"
            )
        return current

    def _move_pointer(self, identity: dict, current: dict | None, change: dict):
        self.verify_version(identity["model_version"], identity["model_sha256"])
        pointer = {
            "model_version": identity["model_version"],
            "model_sha256": identity["model_sha256"],
            "metadata_sha256": identity["metadata_sha256"],
            "previous": None
            if current is None
            else {
                "model_version": current["model_version"],
                "model_sha256": current["model_sha256"],
            },
            "updated_at": now(),
            **change,
        }
        write_json_atomic(self.pointer, pointer)
        with self.history.open("a") as stream:
            stream.write(json.dumps(pointer, allow_nan=False) + "\n")
        return pointer

    def switch(self, identity: dict, *, expected_current: dict | None, change: dict):
        """Move CURRENT to an already installed version (compare-and-swap)."""
        with self.locked():
            current = self._expect(expected_current)
            return self._move_pointer(identity, current, change)

    def accept(
        self,
        source: Path,
        acceptance: dict,
        *,
        expected_current: dict | None,
        change: dict,
    ) -> dict:
        """Install a bundle and move CURRENT to it under one lock.

        The incumbent is checked before anything is copied, so a stale decision
        leaves accepted/ untouched. If the process stops after the install but
        before the pointer moves, the new version exists but is not current;
        rerunning the same command reuses the identical bytes.
        """
        with self.locked():
            current = self._expect(expected_current)
            installed = self.install(source, acceptance)
            return self._move_pointer(installed, current, change)

    def status(self) -> dict:
        current = self.read_current()
        versions = []
        if self.accepted.exists():
            for directory in sorted(self.accepted.iterdir()):
                if not directory.is_dir() or directory.name.startswith("."):
                    continue
                try:
                    identity = bundle_identity(directory)
                    versions.append({**identity, "bytes_verified": True})
                except (StoreError, OSError, ValueError) as error:
                    versions.append(
                        {"model_version": directory.name, "error": str(error)}
                    )
        partial = [
            str(path.relative_to(self.root))
            for parent in (self.accepted, self.candidates)
            if parent.exists()
            for path in parent.iterdir()
            if path.name.startswith(".partial-")
        ]
        history = self.history.read_text().splitlines() if self.history.exists() else []
        return {
            "store": str(self.root),
            "current": current,
            "current_bytes_verified": _verified(self, current),
            "previous_bytes_verified": _verified(
                self, current.get("previous") if current else None
            ),
            "accepted_versions": versions,
            "candidates": sorted(
                path.name
                for path in self.candidates.iterdir()
                if path.is_dir() and not path.name.startswith(".")
            )
            if self.candidates.exists()
            else [],
            "partial_outputs": sorted(partial),
            "pointer_changes": len(history),
            "lock_held": self.lock_path.exists(),
        }


def _verified(store: Store, reference: dict | None) -> bool | None:
    if reference is None:
        return None
    try:
        store.verify_version(reference["model_version"], reference["model_sha256"])
    except (StoreError, OSError, ValueError, KeyError):
        return False
    return True
