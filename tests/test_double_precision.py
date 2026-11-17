import copy
import math
import pathlib
import sys

import pytest
import yaml

from dbt_scenario import errors, loader

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = ROOT / "examples/shop"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", 0.0),
        ("-0.0", -0.0),
        ("0.1", 0.1),
        ("0.10000000000000002", math.nextafter(0.1, math.inf)),
        ("1.25e-30", 1.25e-30),
        ("1.7976931348623157e308", sys.float_info.max),
        ("5e-324", math.ulp(0.0)),
        ("1e-320", 1e-320),
    ],
)
def test_double_precision_converts_quoted_decimal_values_to_binary64(
    value, expected
):
    assert loader.sql_type("double precision") == "double precision"
    actual = loader.converted(value, "double precision")
    assert type(actual) is float
    assert actual == expected
    assert math.copysign(1, actual) == math.copysign(1, expected)
    assert loader.converted(None, "double precision") is None


@pytest.mark.parametrize(
    "value",
    [
        0.1,
        1,
        True,
        float("nan"),
        float("inf"),
        float("-inf"),
        "NaN",
        "Infinity",
        "-Infinity",
        ".nan",
        "1e309",
        "-1e309",
        "1e-324",
        "-1e-9999",
        "1_000",
        " 1.0",
        "1.0 ",
        "0x1.0p0",
        "1,25",
        "synthetic.private@example.invalid",
    ],
)
def test_double_precision_rejects_nonfinite_lossy_or_unquoted_values(value):
    with pytest.raises(errors.ScenarioError, match="INVALID_TYPED_VALUE"):
        loader.converted(value, "double precision")


def test_distinct_decimal_keys_that_round_to_one_double_are_duplicate_keys(
    tmp_path,
):
    data = copy.deepcopy(
        loader.load_scenario(PROJECT / "scenarios/orders.yml", PROJECT).data
    )
    data["output"] = {
        "columns": {"key": "double precision"},
        "primary_key": ["key"],
    }
    data["steps"] = [data["steps"][0]]
    data["steps"][0]["expect"] = {
        "rows": [{"key": "0.1"}, {"key": "0.10000000000000001"}]
    }
    path = tmp_path / "scenario.yml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(errors.ScenarioError, match="INVALID_EXPECTED_KEY"):
        loader.load_scenario(path, tmp_path)
