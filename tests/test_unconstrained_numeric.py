import copy
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
import yaml

from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import converted, load_scenario, sql_type

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "examples/shop"


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "-0.00",
        "0e1000000000",
        "0.10000000000000000000000000000000000001",
        "9" * 150 + "." + "1" * 150,
        "1e131071",
        "1e-16383",
        "-1e-16383",
        "+.125e2",
    ],
)
def test_native_numeric_preserves_exact_finite_values_without_context_rounding(value):
    with localcontext() as context:
        context.prec = 2
        context.Emax = 9
        context.Emin = -9
        context.clear_flags()
        assert sql_type("numeric") == "numeric"
        actual = converted(value, "numeric")
        assert type(actual) is Decimal
        assert actual == Decimal(value)
        assert not any(context.flags.values())
    assert converted(None, "numeric") is None


@pytest.mark.parametrize(
    "value",
    [
        0.1,
        1,
        True,
        Decimal("1.25"),
        float("nan"),
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        "1e131072",
        "-1e131072",
        "1e-16384",
        "0e-16384",
        "1.0e-16383",
        "1e-1000000000",
        "1_000",
        " 1.25",
        "1.25 ",
        "0x10",
        "1,25",
        "synthetic.private@example.invalid",
    ],
)
def test_native_numeric_rejects_ambiguous_nonfinite_or_out_of_range_values(value):
    with pytest.raises(ScenarioError, match="INVALID_TYPED_VALUE"):
        converted(value, "numeric")


def test_native_numeric_expected_keys_use_value_equality_not_decimal_spelling(tmp_path):
    data = copy.deepcopy(load_scenario(PROJECT / "scenarios/orders.yml", PROJECT).data)
    data["output"] = {"columns": {"key": "numeric"}, "primary_key": ["key"]}
    data["steps"] = [data["steps"][0]]
    data["steps"][0]["expect"] = {"rows": [{"key": "1e-100"}, {"key": "10e-101"}]}
    path = tmp_path / "scenario.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ScenarioError, match="INVALID_EXPECTED_KEY"):
        load_scenario(path, tmp_path)
