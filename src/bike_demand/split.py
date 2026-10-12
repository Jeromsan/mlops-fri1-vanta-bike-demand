"""Chronological partitions; test targets are never evaluated in Week 1."""

import pandas as pd

WINDOWS = {
    "train": ("2011-01-01", "2011-12-31"),
    "validation": ("2012-01-01", "2012-06-30"),
    "test": ("2012-07-01", "2012-12-31"),
}


def split_data(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
<<<<<<< HEAD
    dates = frame["dteday"]
    partitions = {
        name: frame.loc[
            dates.between(pd.Timestamp(start), pd.Timestamp(end))
        ].sort_values(["dteday", "hr", "instant"], kind="mergesort")
        for name, (start, end) in WINDOWS.items()
    }
    if sum(map(len, partitions.values())) != len(frame):
=======
    ordered = frame.sort_values(["dteday", "hr", "instant"])
    assignments = pd.Series(0, index=ordered.index)
    partitions = {}
    for name, (start, end) in WINDOWS.items():
        mask = ordered["dteday"].between(start, end)
        assignments += mask.astype(int)
        partitions[name] = ordered.loc[mask].copy()
    if (assignments > 1).any():
        raise ValueError("split: partitions must be disjoint")
    if (assignments != 1).any():
>>>>>>> e7025fd (Complete Lab 2 validated and tracked baseline)
        raise ValueError("split: partitions must be complete")
    if any(part.empty for part in partitions.values()):
        raise ValueError("split: partitions must be nonempty")
    return partitions


def partition_summary(partitions: dict[str, pd.DataFrame]) -> dict:
    return {
        name: {
            "rows": len(part),
            "date_min": str(part["dteday"].min().date()),
            "date_max": str(part["dteday"].max().date()),
        }
        for name, part in partitions.items()
    }
