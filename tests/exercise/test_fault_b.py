from pathlib import Path

import pandas as pd
import pytest

from bike_demand.validate import load_data

pytestmark = pytest.mark.exercise
CONTROL = Path(__file__).parents[1] / "fixtures/missing-hours.csv"


def test_fault_b_infinite_count_is_rejected(tmp_path):
    valid = load_data(CONTROL)
    assert len(valid) == 6
    invalid = pd.read_csv(CONTROL).astype({"cnt": float})
    invalid.loc[0, "cnt"] = float("inf")
    path = tmp_path / "infinite-count.csv"
    invalid.to_csv(path, index=False)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="cnt: require finite nonnegative integers"):
        load_data(path)
    assert path.read_bytes() == before
