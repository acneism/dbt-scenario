import copy
import pathlib
import shutil

import pytest
import yaml

from dbt_scenario import config as scenario_config
from dbt_scenario import errors, loader
from dbt_scenario import project as scenario_project

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = ROOT / "examples/shop"


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("missing_rows", "INVALID_FIXTURE_FILE"),
        ("scalar_rows", "INVALID_FIXTURE_SIZE"),
        ("mapping_rows", "INVALID_FIXTURE_SIZE"),
        ("scalar_row", "FIXTURE_COLUMNS_MISMATCH"),
        ("missing_column", "FIXTURE_COLUMNS_MISMATCH"),
        ("extra_column", "FIXTURE_COLUMNS_MISMATCH"),
        ("wrong_type", "INVALID_TYPED_VALUE"),
        ("duplicate_key", "INVALID_EXPECTED_KEY"),
        ("null_key", "INVALID_EXPECTED_KEY"),
    ],
)
def test_malformed_expected_fixture_is_rejected_before_execution(
    tmp_path, fault, reason
):
    scenario = copy.deepcopy(
        loader.load_scenario(PROJECT / "scenarios/orders.yml", PROJECT).data
    )
    rows = scenario["steps"][0]["expect"]["rows"]
    payload = {"rows": rows}
    if fault == "missing_rows":
        payload = {"unknown": rows}
    elif fault == "scalar_rows":
        payload["rows"] = "synthetic.private@example.invalid"
    elif fault == "mapping_rows":
        payload["rows"] = rows[0]
    elif fault == "scalar_row":
        payload["rows"] = ["synthetic.private@example.invalid"]
    elif fault == "missing_column":
        rows[0].pop("amount")
    elif fault == "extra_column":
        rows[0]["extra"] = "synthetic.private@example.invalid"
    elif fault == "wrong_type":
        rows[0]["amount"] = "synthetic.private@example.invalid"
    elif fault == "duplicate_key":
        rows.append(rows[0].copy())
    elif fault == "null_key":
        rows[0]["order_id"] = None
    scenario["steps"][0]["expect"] = {"fixture": "expected.yml"}
    (tmp_path / "expected.yml").write_text(yaml.safe_dump(payload))
    path = tmp_path / "scenario.yml"
    path.write_text(yaml.safe_dump(scenario))
    with pytest.raises(errors.ScenarioError, match=reason) as error:
        loader.load_scenario(path, tmp_path)
    assert "synthetic.private@example.invalid" not in str(
        error.value.diagnostic()
    )


@pytest.mark.parametrize(
    "relative,content",
    [
        ("models/fct_orders.sql", "\nselect 1\n"),
        ("macros/new_macro.sql", "{% macro added() %}1{% endmacro %}"),
        ("dbt_project.yml", "\nvars: {new_var: true}\n"),
        ("package-lock.yml", "packages: []\nsha1_hash: changed\n"),
    ],
)
def test_project_fingerprint_changes_for_each_execution_input(
    tmp_path, relative, content
):
    copied = tmp_path / "shop"
    shutil.copytree(
        PROJECT, copied, ignore=shutil.ignore_patterns(".dbt-scenario")
    )
    before = scenario_project.fingerprint(copied)
    path = copied / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((path.read_text() if path.exists() else "") + content)
    assert scenario_project.fingerprint(copied) != before


def test_fixture_change_updates_both_fixture_and_scenario_fingerprints(
    tmp_path,
):
    copied = tmp_path / "shop"
    shutil.copytree(
        PROJECT, copied, ignore=shutil.ignore_patterns(".dbt-scenario")
    )
    scenario_path = copied / "scenarios/orders.yml"
    before = loader.load_scenario(scenario_path, copied)
    fixture_path = copied / "scenarios/fixtures/initial.yml"
    fixture = yaml.safe_load(fixture_path.read_text())
    fixture["rows"][0]["amount"] = "123.45"
    fixture_path.write_text(yaml.safe_dump(fixture))
    after = loader.load_scenario(scenario_path, copied)
    assert after.fixture_hashes != before.fixture_hashes
    assert after.fingerprint != before.fingerprint


def test_project_copy_and_mapping_do_not_modify_original_files(tmp_path):
    copied = tmp_path / "shop"
    shutil.copytree(
        PROJECT, copied, ignore=shutil.ignore_patterns(".dbt-scenario")
    )
    original = {
        path.relative_to(copied): path.read_bytes()
        for path in copied.rglob("*")
        if path.is_file()
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = scenario_config.Config(
        copied,
        {
            "host": "localhost",
            "port": 5432,
            "dbname": "test",
            "user": "test",
            "password": "synthetic-test-password",
        },
    )
    project = scenario_project.Project(config, workspace, "dsc_actual")
    scenario = loader.load_scenario(copied / "scenarios/orders.yml", copied)
    project.install_mapping(scenario.data, "dsc_inputs")
    assert original == {
        path.relative_to(copied): path.read_bytes()
        for path in copied.rglob("*")
        if path.is_file()
    }
