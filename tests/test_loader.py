import copy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from dbt_scenario.cli import main
from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import converted, load_scenario, read_yaml

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "examples" / "shop"
SCENARIO = PROJECT / "scenarios" / "orders.yml"


def inline_example():
    return copy.deepcopy(load_scenario(SCENARIO, PROJECT).data)


def write_scenario(tmp_path, data):
    path = tmp_path / "scenario.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "value,kind",
    [
        (1.1, "numeric(12,2)"),
        (True, "bigint"),
        ("12.345", "numeric(12,2)"),
        ("NaN", "numeric(12,2)"),
        ("2026-01-01T00:00:00", "timestamptz"),
        ("2026-01-01T00:00:00Z", "timestamp"),
        ("a\x00b", "text"),
        (2**63, "bigint"),
    ],
)
def test_rejects_lossy_or_ambiguous_values(value, kind):
    with pytest.raises(ScenarioError, match="INVALID_TYPED_VALUE"):
        converted(value, kind)


def test_preserves_decimal_and_timezone():
    assert converted("9999999999.99", "numeric(12,2)") == Decimal("9999999999.99")
    assert converted("2026-01-01T03:00:00+03:00", "timestamptz") == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "text,reason",
    [
        ("name: one\nname: two\n", "DUPLICATE_YAML_KEY"),
        ("one: &a []\ntwo: *a\n", "YAML_ALIAS_UNSUPPORTED"),
        ("x: !!python/object/apply:os.system ['echo unsafe']", "INVALID_YAML"),
    ],
)
def test_rejects_unsafe_yaml(tmp_path, text, reason):
    path = tmp_path / "unsafe.yml"
    path.write_text(text)
    with pytest.raises(ScenarioError, match=reason):
        read_yaml(path)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda d: d.update(unknown=True), "INVALID_SCENARIO_SCHEMA"),
        (lambda d: d["steps"][0]["run"].update(mode="incremental"), "INVALID_STEP_ORDER"),
        (lambda d: d["steps"][2]["expect"].update(same_as="future"), "INVALID_SAME_AS_REFERENCE"),
        (lambda d: d["steps"][0].pop("inputs"), "UNINITIALIZED_INPUT"),
        (
            lambda d: d["output"]["columns"].update(amount="text; drop schema public"),
            "UNSUPPORTED_COLUMN_TYPE",
        ),
        (
            lambda d: d["steps"][0]["expect"]["rows"].append(
                d["steps"][0]["expect"]["rows"][0].copy()
            ),
            "INVALID_EXPECTED_KEY",
        ),
    ],
)
def test_rejects_invalid_scenarios(tmp_path, mutation, reason):
    data = inline_example()
    mutation(data)
    with pytest.raises(ScenarioError, match=reason):
        load_scenario(write_scenario(tmp_path, data), tmp_path)


def test_blocks_fixture_path_escape(tmp_path):
    data = inline_example()
    data["steps"][0]["expect"] = {"fixture": "../outside.yml"}
    with pytest.raises(ScenarioError, match="INVALID_FIXTURE_PATH"):
        load_scenario(write_scenario(tmp_path, data), tmp_path)


def test_var_change_changes_fingerprint(tmp_path):
    data = inline_example()
    path = write_scenario(tmp_path, data)
    before = load_scenario(path, tmp_path).fingerprint
    data["steps"][0]["run"]["vars"] = {"as_of": "2026-01-01"}
    after = load_scenario(write_scenario(tmp_path, data), tmp_path).fingerprint
    assert before != after


def test_cli_empty_selection_is_error(monkeypatch):
    monkeypatch.setenv("DSC_TEST_PASSWORD", "disposable-test-password")
    result = CliRunner().invoke(main, ["test", "--config", str(ROOT / "scenario-runner.yml")])
    assert result.exit_code == 2
    assert "NO_SCENARIOS_SELECTED" in result.output
