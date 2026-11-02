import copy
import json
import os
import shutil
from pathlib import Path

import psycopg
import pytest
import yaml
from click.testing import CliRunner

from dbt_scenario.cli import main
from dbt_scenario.config import load_config
from dbt_scenario.loader import load_scenario
from dbt_scenario.project import fingerprint
from dbt_scenario.runner import run_scenario

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.integration


@pytest.fixture
def project(tmp_path):
    if "DSC_TEST_PASSWORD" not in os.environ:
        pytest.skip("DSC_TEST_PASSWORD is required for disposable PostgreSQL")
    config = load_config(ROOT / "scenario-runner.yml")
    copied = tmp_path / "shop"
    shutil.copytree(config.project_dir, copied)
    config.project_dir = copied
    scenario = load_scenario(copied / "scenarios" / "orders.yml", copied)
    return config, scenario, tmp_path / "reports"


@pytest.mark.parametrize("strategy", ["delete+insert", "merge"])
def test_real_incremental_update_late_arrival_retry(project, strategy):
    config, scenario, reports = project
    for step in scenario.data["steps"]:
        step["run"]["vars"] = {"strategy": strategy}
    before = fingerprint(config.project_dir)
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "PASS", result
    assert result["cleanup_status"] == "CLEANED"
    assert result["steps"][1]["observed_mode_evidence"]["operation"] == strategy
    assert [s["actual_rows"] for s in result["steps"]] == [2, 3, 3]
    assert fingerprint(config.project_dir) == before
    with psycopg.connect(**config.connection_kwargs()) as connection:
        assert not connection.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname LIKE %s",
            [f"dsc_{result['run_id'][:20]}_%"],
        ).fetchall()


def test_detects_wrong_watermark_and_stops_dependent_steps(project):
    config, scenario, reports = project
    model = config.project_dir / "models" / "fct_orders.sql"
    model.write_text(
        model.read_text()
        .replace("where updated_at >=", "where event_at >")
        .replace("max(updated_at)", "max(event_at)")
    )
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "FAIL", result
    assert result["steps"][1]["diff_counts"] == {"missing": 1, "unexpected": 0, "changed": 1}
    assert result["steps"][2]["status"] == "NOT_RUN"


def test_reports_duplicate_keys_instead_of_collapsing_append_rows(project):
    config, scenario, reports = project
    for step in scenario.data["steps"]:
        step["run"]["vars"] = {"strategy": "append"}
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "FAIL", result
    assert result["steps"][1]["reason_code"] == "DUPLICATE_KEY"


def test_detects_equal_sum_value_swap(project):
    config, scenario, reports = project
    expected = scenario.data["steps"][1]["expect"]["rows"]
    expected[0]["amount"], expected[1]["amount"] = expected[1]["amount"], expected[0]["amount"]
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "FAIL", result
    assert result["steps"][1]["diff_counts"] == {"missing": 0, "unexpected": 0, "changed": 2}


def test_ref_input_is_fixtured_without_running_upstream_sql(project):
    config, scenario, reports = project
    model = config.project_dir / "models" / "fct_orders.sql"
    model.write_text(model.read_text().replace("source('raw', 'orders')", "ref('stg_orders')"))
    (config.project_dir / "models" / "stg_orders.sql").write_text(
        "select * from table_that_must_never_be_read"
    )
    scenario.data["inputs"]["orders"]["node"] = "model.shop.stg_orders"
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "PASS", result


def test_errors_are_redacted_and_never_pass(project):
    config, scenario, reports = project
    secret = "synthetic.person@example.invalid"
    (config.project_dir / "models" / "fct_orders.sql").write_text(
        "{{ exceptions.raise_compiler_error('" + secret + "') }}"
    )
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "ERROR", result
    assert result["reason_code"] == "DBT_EXECUTION_ERROR"
    for path in (reports / result["run_id"]).iterdir():
        assert path.is_file()
        assert secret not in path.read_text()
        assert config.database["password"] not in path.read_text()


def test_cli_nonzero_and_json_junit_artifacts(project, tmp_path):
    config, scenario, reports = project
    data = copy.deepcopy(scenario.data)
    data["steps"][0]["expect"]["rows"][0]["amount"] = "99.00"
    path = config.project_dir / "scenarios" / "bad.yml"
    path.write_text(yaml.safe_dump(data))
    runner_config = yaml.safe_load((ROOT / "scenario-runner.yml").read_text())
    runner_config["project_dir"] = str(config.project_dir)
    config_path = tmp_path / "runner.yml"
    config_path.write_text(yaml.safe_dump(runner_config))
    result = CliRunner().invoke(
        main,
        [
            "test",
            "--config",
            str(config_path),
            "--scenario",
            str(path),
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 1, result.output
    summaries = list(reports.glob("*/summary.json"))
    assert len(summaries) == 1
    assert json.loads(summaries[0].read_text())["overall_status"] == "FAIL"
    assert summaries[0].with_name("junit.xml").is_file()
