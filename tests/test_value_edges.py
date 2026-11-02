import copy
import hashlib
import subprocess
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
import yaml

from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import converted, load_scenario

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "examples/shop"


@pytest.mark.parametrize("precision,scale", [(38, 2), (99, 0), (99, 99)])
def test_decimal_precision_is_independent_of_the_python_context(precision, scale):
    integral = "9" * (precision - scale) or "0"
    value = integral + ("." + "9" * scale if scale else "")
    with localcontext() as context:
        context.prec = 6
        assert converted(value, f"numeric({precision},{scale})") == Decimal(value)
        assert converted("-" + value, f"numeric({precision},{scale})") == Decimal("-" + value)


@pytest.mark.parametrize(
    "value,kind",
    [
        ("1000000000000000000000000000000000000.00", "numeric(38,2)"),
        ("1.001", "numeric(38,2)"),
        ("1E+999999", "numeric(38,2)"),
        ("2026-01-01T00:00:00.1234567", "timestamp"),
        ("2026-01-01T00:00:00.0000001Z", "timestamptz"),
    ],
)
def test_rejects_values_that_need_rounding_or_truncation(value, kind):
    with pytest.raises(ScenarioError, match="INVALID_TYPED_VALUE"):
        converted(value, kind)


def test_fixture_snapshot_is_cached_without_sharing_mutable_rows(tmp_path, monkeypatch):
    from dbt_scenario import loader

    reads = []
    original = loader.read_yaml_document
    fixture = PROJECT / "scenarios/fixtures/initial.yml"

    def observed(path):
        reads.append(path.resolve())
        return original(path)

    monkeypatch.setattr(loader, "read_yaml_document", observed)
    scenario = load_scenario(PROJECT / "scenarios/orders.yml", PROJECT)
    assert reads.count(fixture.resolve()) == 1
    expected = scenario.data["steps"][0]["expect"]["rows"]
    inputs = scenario.data["steps"][0]["inputs"]["orders"]["replace"]["rows"]
    expected[0]["amount"] = "999.00"
    assert inputs[0]["amount"] == "10.00"
    assert (
        scenario.fixture_hashes["scenarios/fixtures/initial.yml"]
        == hashlib.sha256(fixture.read_bytes()).hexdigest()
    )


def test_yaml_numeric_column_name_is_a_validation_error(tmp_path):
    scenario = copy.deepcopy(load_scenario(PROJECT / "scenarios/orders.yml", PROJECT).data)
    scenario["output"]["columns"] = {True: "integer"}
    path = tmp_path / "invalid.yml"
    path.write_text(yaml.safe_dump(scenario))
    with pytest.raises(ScenarioError, match="INVALID_COLUMN_NAME"):
        load_scenario(path, tmp_path)


def test_yaml_nesting_is_bounded_before_construction(tmp_path):
    from dbt_scenario.loader import read_yaml

    path = tmp_path / "deep.yml"
    path.write_text("[" * 129 + "0" + "]" * 129)
    with pytest.raises(ScenarioError, match="YAML_NESTING_LIMIT"):
        read_yaml(path)


def test_python_yaml_fallback_keeps_validation_rules(tmp_path):
    duplicate = tmp_path / "duplicate.yml"
    duplicate.write_text("key: 1\nkey: 2\n")
    alias = tmp_path / "alias.yml"
    alias.write_text("first: &a []\nsecond: *a\n")
    program = (
        "import sys,yaml; from pathlib import Path; "
        "yaml.__dict__.pop('CSafeLoader',None); "
        "from dbt_scenario.loader import read_yaml; "
        "from dbt_scenario.errors import ScenarioError\n"
        "for path,code in zip(sys.argv[1:],['DUPLICATE_YAML_KEY','YAML_ALIAS_UNSUPPORTED']):\n"
        "    try:\n"
        "        read_yaml(Path(path))\n"
        "    except ScenarioError as error:\n"
        "        assert error.code == code\n"
        "    else:\n"
        "        raise AssertionError('invalid YAML passed fallback')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(duplicate), str(alias)],
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
