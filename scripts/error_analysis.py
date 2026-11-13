"""Validation error analysis of one trusted bundle; input for candidate hypotheses.

    uv run --locked python scripts/error_analysis.py artifacts/accepted/<version>

Scores the validation window only (Jan-Jun 2012). It never trains, never
selects a model and never reads held-test labels.
"""

import json
import sys
from pathlib import Path

import numpy as np

from bike_demand.api import load_artifact
from bike_demand.split import split_data
from bike_demand.validate import FEATURES, load_data

PEAK_HOURS = (7, 8, 9, 17, 18, 19)


def main(argv: list[str]) -> int:
    directory = Path(argv[0])
    loaded = load_artifact(directory)
    partitions = split_data(load_data("data/raw/hour.csv"))
    train, validation = partitions["train"], partitions["validation"]
    predictions = loaded.model.predict(validation.loc[:, list(FEATURES)])
    labels = validation["cnt"].to_numpy()
    errors = np.abs(labels - predictions)
    peak = (
        (validation["workingday"] == 1) & validation["hr"].isin(PEAK_HOURS)
    ).to_numpy()
    by_month = {
        str(month): float(errors[(validation["mnth"] == month).to_numpy()].mean())
        for month in sorted(validation["mnth"].unique())
    }
    result = {
        "record_type": "error_analysis",
        "model_version": loaded.version,
        "model_sha256": loaded.sha256,
        "window": "validation 2012-01-01..2012-06-30",
        "rows": int(len(validation)),
        "validation_mae": float(errors.mean()),
        "working_day_peak_hours": {
            "hours": list(PEAK_HOURS),
            "rows": int(peak.sum()),
            "mae": float(errors[peak].mean()),
            "share_of_absolute_error": float(errors[peak].sum() / errors.sum()),
        },
        "mean_signed_error": float((predictions - labels).mean()),
        "mean_demand": {
            "train_2011": float(train["cnt"].mean()),
            "validation_2012": float(labels.mean()),
        },
        "mae_by_month": by_month,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
