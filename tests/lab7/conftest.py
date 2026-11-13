"""A small committed project in a temporary Git repository.

The data is a deterministic sample of the frozen course CSV (every 25th row), so
the chronological windows keep their meaning while tests stay fast. The
incumbent is trained here; no team artifact or course model is loaded.
"""

import json
import subprocess
from pathlib import Path

import joblib
import pandas as pd
import pytest
import yaml
from sklearn.ensemble import RandomForestRegressor

from bike_demand.pipeline import DATA, adopt
from bike_demand.preflight import sha256
from bike_demand.split import split_data
from bike_demand.validate import FEATURES, load_data

REPO = Path(__file__).parents[2]
SETTINGS = {
    "n_estimators": 10,
    "max_depth": 6,
    "min_samples_leaf": 1,
    "random_state": 42,
    "n_jobs": 1,
}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def commit(root: Path, message: str = "test commit") -> str:
    git(root, "add", "-A", "--", ".")
    git(root, "commit", "-q", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD")


def policy_for(rows: dict, **changes) -> dict:
    policy = {
        "policy_version": "test-v1",
        "rationale": {"note": "test policy"},
        "primary_metric": {
            "name": "validation_mae",
            "unit": "rentals per hour",
            "direction": "lower_is_better",
        },
        "evaluation": {"window": "validation", "expected_rows": rows},
        "quality": {"min_gain_vs_naive": 1.0, "min_gain_vs_incumbent": 0.0},
        "operation": {
            "max_model_bytes": 50_000_000,
            "max_p95_predict_ms": 1000.0,
            "latency_requests": 20,
        },
        "candidate_settings": {
            "allowed": {
                "n_estimators": {"min": 1, "max": 200},
                "max_depth": {"min": 1, "max": 40, "allow_none": True},
                "min_samples_leaf": {"min": 1, "max": 50},
            },
            "fixed": {"random_state": 42, "n_jobs": 1},
        },
        "budget": {"max_evaluated_candidates": 5},
    }
    for section, values in changes.items():
        policy[section] = {**policy[section], **values}
    return policy


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.store = root / "artifacts"
        self.decisions = root / "reports/decisions"
        self.promotions = root / "reports/promotions"
        self.policy = root / "configs/gate-policy.yaml"
        frame = pd.read_csv(REPO / DATA)
        sample = frame[frame["instant"] % 25 == 0]
        data = root / DATA
        data.parent.mkdir(parents=True)
        sample.to_csv(data, index=False)
        (root / "data/manifest.json").write_text(
            json.dumps(
                {
                    "sha256": sha256(data),
                    "bytes": data.stat().st_size,
                    "header": list(sample.columns),
                    "rows": len(sample),
                }
            )
        )
        self.partitions = split_data(load_data(data))
        self.rows = {name: len(part) for name, part in self.partitions.items()}
        self.write_policy()
        self.candidate = self.write_candidate("c1", SETTINGS)

    def write_policy(self, **changes) -> Path:
        self.policy.parent.mkdir(parents=True, exist_ok=True)
        self.policy.write_text(yaml.safe_dump(policy_for(self.rows, **changes)))
        return self.policy

    def write_candidate(self, name: str, settings: dict) -> Path:
        path = self.root / f"configs/candidates/{name}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {
                    "data": DATA,
                    "features": list(FEATURES),
                    "model": settings,
                    "candidate": {"name": name, "hypothesis": "test hypothesis"},
                },
                sort_keys=False,
            )
        )
        return path

    def incumbent_bundle(self, version: str = "incumbent-1", scale: float = 1.0):
        """A trusted test incumbent; scale > 1 makes it deliberately worse."""
        train = self.partitions["train"]
        model = RandomForestRegressor(**SETTINGS)
        model.fit(train.loc[:, list(FEATURES)], train["cnt"] * scale)
        directory = self.root / "incoming" / version
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, directory / "model.joblib")
        metadata = {
            "model_version": version,
            "features": list(FEATURES),
            "data_sha256": sha256(self.root / DATA),
            "training_commit": "test",
            "working_tree_dirty": False,
            "model_sha256": sha256(directory / "model.joblib"),
        }
        (directory / "model-metadata.json").write_text(json.dumps(metadata))
        return directory, metadata

    def adopt(self, scale: float = 1.0) -> dict:
        directory, metadata = self.incumbent_bundle(scale=scale)
        pointer, _ = adopt(
            self.root,
            self.store,
            directory,
            metadata["model_version"],
            metadata["model_sha256"],
            "Test Owner",
            "test incumbent",
            self.promotions,
        )
        return pointer


@pytest.fixture
def project(tmp_path, monkeypatch) -> Project:
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    # Same rule as the team repository: models and tracking stay out of Git.
    (root / ".gitignore").write_text("artifacts/\ntracking/\nincoming/\n")
    created = Project(root)
    commit(root, "project inputs and policy")
    monkeypatch.chdir(root)
    return created
