import copy
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
import pytest
import yaml
from click.testing import CliRunner
from psycopg import sql

from dbt_scenario.cli import main
from dbt_scenario.config import Config, load_config
from dbt_scenario.database import Database
from dbt_scenario.deadline import Deadline
from dbt_scenario.environment import process_environment
from dbt_scenario.errors import ScenarioError
from dbt_scenario.initialize import initialize
from dbt_scenario.journal import Journal
from dbt_scenario.lifecycle import cleanup_run, finish_run
from dbt_scenario.loader import load_scenario
from dbt_scenario.process import run_process
from dbt_scenario.project import Project, fingerprint
from dbt_scenario.runner import run_scenario

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.integration


@pytest.fixture
def project(tmp_path):
    if "DSC_TEST_PASSWORD" not in os.environ:
        pytest.skip("DSC_TEST_PASSWORD is required for disposable PostgreSQL")
    config = load_config(ROOT / "scenario-runner.yml")
    copied = tmp_path / "shop"
    shutil.copytree(config.project_dir, copied, ignore=shutil.ignore_patterns(".dbt-scenario"))
    config.project_dir = copied
    scenario = load_scenario(copied / "scenarios" / "orders.yml", copied)
    return config, scenario, tmp_path / "reports"


def config_file(config, directory):
    data = yaml.safe_load((ROOT / "scenario-runner.yml").read_text())
    data["project_dir"] = str(config.project_dir)
    data["step_timeout"] = config.step_timeout
    data["scenario_timeout"] = config.scenario_timeout
    data["env_allowlist"] = list(config.project_env)
    path = directory / "runner.yml"
    path.write_text(yaml.safe_dump(data))
    return path


def existing_schemas(config, journal):
    with psycopg.connect(**config.connection_kwargs()) as connection:
        return connection.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname=ANY(%s)",
            [journal.data["schemas"]],
        ).fetchall()


def slow_model(config):
    model = config.project_dir / "models" / "fct_orders.sql"
    model.write_text(
        model.read_text().replace(
            "from {{ source('raw', 'orders') }}",
            "from {{ source('raw', 'orders') }} cross join (select pg_sleep(60)) delay",
        )
    )


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


def test_kept_failure_can_be_cleaned_twice_from_cli(project, tmp_path):
    config, scenario, reports = project
    scenario.data["steps"][0]["expect"]["rows"][0]["amount"] = "99.00"
    result = run_scenario(scenario, config, reports, keep_on_failure=True)
    assert result["overall_status"] == "FAIL", result
    assert result["cleanup_status"] == "KEPT"
    journal = Journal.load(config, result["run_id"])
    assert len(existing_schemas(config, journal)) == 3
    path = config_file(config, tmp_path)
    try:
        for _ in range(2):
            response = CliRunner().invoke(
                main,
                [
                    "cleanup",
                    "--config",
                    str(path),
                    "--run-id",
                    result["run_id"],
                ],
            )
            assert response.exit_code == 0, response.output
        assert not existing_schemas(config, journal)
        assert Journal.load(config, result["run_id"]).data["state"] == "CLEANED"
    finally:
        cleanup_run(config, result["run_id"])


def test_cleanup_refuses_an_active_runner(project):
    config, _, _ = project
    database = Database(config)
    journal = Journal.create(config, uuid.uuid4().hex)
    try:
        database.create_schemas(journal)
        with pytest.raises(ScenarioError, match="RUN_STILL_ACTIVE"):
            cleanup_run(config, journal.data["run_id"])
        assert len(existing_schemas(config, journal)) == 3
        assert Journal.load(config, journal.data["run_id"]).data["state"] == "RUNNING"
    finally:
        database.close()
        cleanup_run(config, journal.data["run_id"])


def test_cleanup_validates_every_marker_before_deleting_anything(project):
    config, _, _ = project
    database = Database(config)
    journal = Journal.create(config, uuid.uuid4().hex)
    database.create_schemas(journal)
    name = journal.data["schemas"][1]
    database.execute(sql.SQL("COMMENT ON SCHEMA {} IS 'not-owned'").format(sql.Identifier(name)))
    database.close()
    try:
        with pytest.raises(ScenarioError, match="CLEANUP_OWNERSHIP_MISMATCH"):
            cleanup_run(config, journal.data["run_id"])
        assert len(existing_schemas(config, journal)) == 3
        assert Journal.load(config, journal.data["run_id"]).data["state"] == "CLEANUP_FAILED"
    finally:
        with psycopg.connect(**config.connection_kwargs(), autocommit=True) as connection:
            connection.execute(
                sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                    sql.Identifier(name), sql.Literal(journal.marker())
                )
            )
        cleanup_run(config, journal.data["run_id"])


def test_cleanup_never_cascades_into_another_run(project):
    config, _, _ = project
    first, second = [Journal.create(config, uuid.uuid4().hex) for _ in range(2)]
    databases = [Database(config), Database(config)]
    try:
        for database, journal in zip(databases, [first, second], strict=True):
            database.create_schemas(journal)
        table = sql.Identifier(first.data["schemas"][0], "owned")
        view = sql.Identifier(second.data["schemas"][0], "foreign_view")
        databases[0].execute(sql.SQL("CREATE TABLE {} (id integer)").format(table))
        databases[1].execute(sql.SQL("CREATE VIEW {} AS SELECT * FROM {}").format(view, table))
    finally:
        for database in databases:
            database.close()
    try:
        with pytest.raises(psycopg.errors.DependentObjectsStillExist):
            cleanup_run(config, first.data["run_id"])
        assert len(existing_schemas(config, first)) == 3
        assert len(existing_schemas(config, second)) == 3
        with psycopg.connect(**config.connection_kwargs(), autocommit=True) as connection:
            connection.execute(sql.SQL("SELECT * FROM {}").format(view))
            connection.execute(sql.SQL("DROP VIEW {} RESTRICT").format(view))
    finally:
        cleanup_run(config, first.data["run_id"])
        cleanup_run(config, second.data["run_id"])


def test_deadline_cancels_sql_and_rolls_back_all_input_updates(project):
    config, _, _ = project
    database = Database(config)
    journal = Journal.create(config, uuid.uuid4().hex)
    try:
        database.create_schemas(journal)
        name = journal.data["schemas"][1]
        database.replace(name, "input", {"id": "integer"}, [{"id": 1}])
        started = time.monotonic()
        with pytest.raises(ScenarioError, match="STEP_TIMEOUT"):
            with database.budget(Deadline(0.25, "STEP_TIMEOUT")):
                with database.connection.transaction():
                    database.replace(name, "input", {"id": "integer"}, [{"id": 2}])
                    database.execute("SELECT pg_sleep(60)")
        assert time.monotonic() - started < 4
        assert database.execute(
            sql.SQL("SELECT id FROM {}.input").format(sql.Identifier(name))
        ).fetchall() == [(1,)]
    finally:
        finish_run(database, journal)
        database.close()


def test_timeout_in_dbt_stops_server_query_and_cleans_schemas(project):
    config, scenario, reports = project
    slow_model(config)
    config.step_timeout = 24
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "ERROR", result
    assert result["reason_code"] == "STEP_TIMEOUT", result
    assert result["cleanup_status"] == "CLEANED", result
    journal = Journal.load(config, result["run_id"])
    assert not existing_schemas(config, journal)
    with psycopg.connect(**config.connection_kwargs()) as connection:
        assert not connection.execute(
            "SELECT 1 FROM pg_stat_activity WHERE application_name=%s AND state='active'",
            [f"dbt-scenario:{journal.data['schemas'][0]}"],
        ).fetchall()


def test_snapshot_is_inside_the_step_deadline(project, monkeypatch):
    config, scenario, reports = project
    config.step_timeout = 24
    original = Database.snapshot

    def delayed_snapshot(database, *args):
        database.execute("SELECT pg_sleep(60)")
        return original(database, *args)

    monkeypatch.setattr(Database, "snapshot", delayed_snapshot)
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "ERROR", result
    assert result["reason_code"] == "STEP_TIMEOUT", result
    assert result["cleanup_status"] == "CLEANED", result


def test_scenario_deadline_also_limits_setup(project):
    config, scenario, reports = project
    config.scenario_timeout = 1
    result = run_scenario(scenario, config, reports)
    assert result["overall_status"] == "ERROR", result
    assert result["reason_code"] == "SCENARIO_TIMEOUT", result
    assert result["duration_ms"] < 10000, result


def test_abandoned_process_resources_can_be_recovered(project, tmp_path):
    config, _, _ = project
    run_id = uuid.uuid4().hex
    path = config_file(config, tmp_path)
    program = (
        "import os,sys; from pathlib import Path; "
        "from dbt_scenario.config import load_config; "
        "from dbt_scenario.database import Database; "
        "from dbt_scenario.journal import Journal; "
        "c=load_config(Path(sys.argv[1])); j=Journal.create(c,sys.argv[2]); "
        "d=Database(c); d.create_schemas(j); os._exit(17)"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(path), run_id],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 17, result.stderr
    journal = Journal.load(config, run_id)
    assert len(existing_schemas(config, journal)) == 3
    cleanup_run(config, run_id)
    assert not existing_schemas(config, journal)


def test_two_cli_processes_do_not_share_state(project, tmp_path):
    config, scenario, reports = project
    path = config_file(config, tmp_path)
    argv = [
        sys.executable,
        "-c",
        "from dbt_scenario.cli import main; main()",
        "test",
        "--config",
        str(path),
        "--scenario",
        str(scenario.path),
        "--report-dir",
        str(reports),
    ]
    processes = [
        subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)
    ]
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=120)
            assert process.returncode == 0, (stdout, stderr)
        summaries = [json.loads(path.read_text()) for path in reports.glob("*/summary.json")]
        assert len(summaries) == 2
        assert len({report["run_id"] for report in summaries}) == 2
        assert all(report["overall_status"] == "PASS" for report in summaries)
        for report in summaries:
            assert not existing_schemas(config, Journal.load(config, report["run_id"]))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGINT delivery")
def test_sigint_cleans_resources_and_returns_130(project, tmp_path):
    config, scenario, reports = project
    slow_model(config)
    path = config_file(config, tmp_path)
    argv = [
        sys.executable,
        "-c",
        "from dbt_scenario.cli import main; main()",
        "test",
        "--config",
        str(path),
        "--scenario",
        str(scenario.path),
        "--report-dir",
        str(reports),
    ]
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        end = time.monotonic() + 45
        while time.monotonic() < end:
            with psycopg.connect(**config.connection_kwargs()) as connection:
                active = connection.execute(
                    "SELECT 1 FROM pg_stat_activity WHERE application_name LIKE 'dbt-scenario:%' "
                    "AND state='active' AND query LIKE '%%pg_sleep%%'"
                ).fetchone()
            if active:
                break
            assert process.poll() is None
            time.sleep(0.1)
        else:
            pytest.fail("dbt never started the slow query")
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 130, (stdout, stderr)
        report = json.loads(next(reports.glob("*/summary.json")).read_text())
        assert report["reason_code"] == "INTERRUPTED", report
        assert report["cleanup_status"] == "CLEANED", report
        assert not existing_schemas(config, Journal.load(config, report["run_id"]))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_initialized_demo_runs_on_real_postgresql(tmp_path):
    if "DSC_TEST_PASSWORD" not in os.environ:
        pytest.skip("DSC_TEST_PASSWORD is required for disposable PostgreSQL")
    destination = tmp_path / "generated-demo"
    initialize(destination, demo=True)
    config = load_config(destination / "scenario-runner.yml")
    scenario = load_scenario(destination / "examples/shop/scenarios/orders.yml", config.project_dir)
    report = run_scenario(scenario, config, tmp_path / "reports")
    assert report["overall_status"] == "PASS", report
    assert report["cleanup_status"] == "CLEANED"
    assert [step["actual_rows"] for step in report["steps"]] == [2, 3, 3]


def test_real_manifest_refuses_custom_macros_before_template_writes(tmp_path, monkeypatch):
    root = tmp_path / "analytics"
    (root / "models").mkdir(parents=True)
    (root / "macros").mkdir()
    (root / "dbt_project.yml").write_text("name: analytics\nconfig-version: 2\n")
    (root / "models/fct_orders.sql").write_text(
        "{{ config(materialized='incremental', unique_key='order_id') }}\n"
        "select order_id from {{ source('raw', 'orders') }}\n"
    )
    columns = [{"name": "order_id", "data_type": "bigint"}]
    (root / "models/schema.yml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "models": [{"name": "fct_orders", "columns": columns}],
                "sources": [
                    {
                        "name": "raw",
                        "tables": [{"name": "orders", "columns": copy.deepcopy(columns)}],
                    }
                ],
            }
        )
    )
    (root / "macros/schema.sql").write_text(
        "{% macro generate_schema_name(custom_schema_name, node) %}"
        "{{ target.schema }}{% endmacro %}"
    )
    config = Config(
        root,
        {
            "host": "127.0.0.1",
            "port": 1,
            "dbname": "offline_metadata_test",
            "user": "offline_metadata_test",
            "password": "unused-synthetic-password",
            "sslmode": "disable",
        },
    )
    _, artifacts = Project(config, tmp_path / "parse", "dsc_metadata_probe").invoke("parse", 120)
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    with monkeypatch.context() as patch:
        patch.delenv("DSC_TEST_PASSWORD", raising=False)
        patch.delenv("DBT_ENV_SECRET_DSC_PASSWORD", raising=False)
        patch.setattr("psycopg.connect", lambda *a, **kw: pytest.fail("database accessed"))
        patch.setattr("subprocess.Popen", lambda *a, **kw: pytest.fail("subprocess started"))
        arguments = [
            "--project-dir",
            str(root),
            "--manifest",
            str(artifacts / "target/manifest.json"),
        ]
        discovered = CliRunner().invoke(main, ["discover", *arguments])
        assert discovered.exit_code == 0, discovered.output
        entry = json.loads(discovered.output)["models"][0]
        assert entry["status"] == "BLOCKED"
        assert entry["reason_code"] == "CUSTOM_MACRO_UNSUPPORTED"
        initialized = CliRunner().invoke(main, ["init", *arguments, "--model", "fct_orders"])
        assert initialized.exit_code == 2, initialized.output
        assert "CUSTOM_MACRO_UNSUPPORTED" in initialized.output
    assert {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == before


def test_metadata_template_from_real_catalog_runs_after_explicit_fixture_edits(
    project, tmp_path, monkeypatch
):
    config, original, reports = project
    native = Database(config)
    journal = Journal.create(config, uuid.uuid4().hex)
    actual, inputs, _ = journal.data["schemas"]
    try:
        native.create_schemas(journal)
        definition = original.data["inputs"]["orders"]
        native.replace(
            inputs,
            "orders",
            definition["columns"],
            original.data["steps"][0]["inputs"]["orders"]["replace"]["rows"],
        )
        sources = config.project_dir / "models/sources.yml"
        document = yaml.safe_load(sources.read_text())
        document["sources"][0]["schema"] = inputs
        sources.write_text(yaml.safe_dump(document))
        profiles = tmp_path / "native_profiles"
        profiles.mkdir()
        profile = {
            key: config.database[key] for key in ["host", "port", "dbname", "user", "sslmode"]
        }
        profile.update(type="postgres", schema=actual, threads=1)
        profile["pass"] = "{{ env_var('DBT_ENV_SECRET_DSC_PASSWORD') }}"
        (profiles / "profiles.yml").write_text(
            yaml.safe_dump({"shop": {"target": "test", "outputs": {"test": profile}}})
        )
        executable = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
        artifacts = tmp_path / "docs_artifacts"
        for command in [["run", "--select", "fct_orders"], ["docs", "generate"]]:
            arguments = [
                str(executable),
                "--no-use-colors",
                "--no-partial-parse",
                "--log-path",
                str(tmp_path / "native_logs"),
                *command,
                "--project-dir",
                str(config.project_dir),
                "--profiles-dir",
                str(profiles),
                "--target-path",
                str(artifacts),
            ]
            assert (
                run_process(
                    arguments,
                    process_environment({}, config.database["password"]),
                    config.project_dir,
                    Deadline(120, "DBT_TIMEOUT"),
                )
                == 0
            )
        model = config.project_dir / "models/fct_orders.sql"
        before = model.read_bytes()
        with monkeypatch.context() as patch:
            patch.setattr("psycopg.connect", lambda *a, **kw: pytest.fail("init accessed database"))
            patch.setattr("subprocess.Popen", lambda *a, **kw: pytest.fail("subprocess started"))
            discovered = CliRunner().invoke(
                main,
                [
                    "discover",
                    "--project-dir",
                    str(config.project_dir),
                    "--manifest",
                    str(artifacts / "manifest.json"),
                    "--catalog",
                    str(artifacts / "catalog.json"),
                ],
            )
            assert discovered.exit_code == 0, discovered.output
            inventory = json.loads(discovered.output)
            assert not inventory["execution_checked"]
            assert inventory["models"] == [
                {
                    "model": "model.shop.fct_orders",
                    "status": "TEMPLATE_READY",
                    "reason_code": None,
                    "input_count": 1,
                }
            ]
            result = CliRunner().invoke(
                main,
                [
                    "init",
                    "--project-dir",
                    str(config.project_dir),
                    "--model",
                    "fct_orders",
                    "--manifest",
                    str(artifacts / "manifest.json"),
                    "--catalog",
                    str(artifacts / "catalog.json"),
                ],
            )
        assert result.exit_code == 0, result.output
        path = config.project_dir / "scenarios/fct_orders.yml"
        data = yaml.safe_load(path.read_text())
        assert data["inputs"]["input_1"]["node"] == "source.shop.raw.orders"
        assert data["output"]["columns"] == original.data["output"]["columns"]
        for index, fixture_name in enumerate(["initial", "updated"]):
            rows = yaml.safe_load(
                (config.project_dir / f"scenarios/fixtures/{fixture_name}.yml").read_text()
            )["rows"]
            data["steps"][index]["inputs"]["input_1"]["replace"]["rows"] = copy.deepcopy(rows)
            data["steps"][index]["expect"]["rows"] = copy.deepcopy(rows)
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        generated = load_config(config.project_dir / "scenario-runner.yml")
        report = run_scenario(load_scenario(path, generated.project_dir), generated, reports)
        assert report["overall_status"] == "PASS", report
        assert report["cleanup_status"] == "CLEANED"
        assert [step["actual_rows"] for step in report["steps"]] == [2, 3, 3]
        assert model.read_bytes() == before
    finally:
        finish_run(native, journal)
        native.close()


def test_project_env_allowlist_reaches_dbt_without_forwarding_other_values(
    project, tmp_path, monkeypatch
):
    config, scenario, reports = project
    monkeypatch.setenv("SCENARIO_ADJUSTMENT", "1.00")
    monkeypatch.setenv("SCENARIO_UNLISTED_SENTINEL", "synthetic.private@example.invalid")
    path = config_file(config, tmp_path)
    settings = yaml.safe_load(path.read_text())
    settings["env_allowlist"] = ["SCENARIO_ADJUSTMENT"]
    path.write_text(yaml.safe_dump(settings))
    config = load_config(path)
    model = config.project_dir / "models/fct_orders.sql"
    code = model.read_text().replace(
        "select order_id, event_at, updated_at, amount",
        "select order_id, event_at, updated_at, "
        "cast(amount + {{ env_var('SCENARIO_ADJUSTMENT') }} as numeric(12,2)) as amount",
    )
    code += (
        "\n{% if env_var('SCENARIO_UNLISTED_SENTINEL', 'absent') != 'absent' %}"
        "\n{{ exceptions.raise_compiler_error('unlisted variable leaked') }}"
        "\n{% endif %}\n"
    )
    model.write_text(code)
    from decimal import Decimal

    for step in scenario.data["steps"]:
        for row in step["expect"].get("rows", []):
            row["amount"] = str(Decimal(row["amount"]) + Decimal("1.00"))
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "PASS", report
    assert report["project_env_names"] == ["SCENARIO_ADJUSTMENT"]
    encoded = json.dumps(report)
    assert "synthetic.private@example.invalid" not in encoded
    assert "1.00" not in encoded


@pytest.mark.parametrize("strategy", ["delete+insert", "merge"])
@pytest.mark.parametrize("historical", [False, True])
def test_incremental_model_can_grow_from_an_empty_initial_table(project, strategy, historical):
    config, _, reports = project
    scenario = load_scenario(config.project_dir / "scenarios/empty-start.yml", config.project_dir)
    for step in scenario.data["steps"]:
        step["run"]["vars"] = {"strategy": strategy}
        if historical:
            snapshots = [update["replace"] for update in step.get("inputs", {}).values()]
            snapshots.append(step["expect"])
            for snapshot in snapshots:
                for row in snapshot.get("rows", []):
                    for column in ["event_at", "updated_at"]:
                        row[column] = (
                            row[column].replace("2026-", "1800-").replace("2025-", "1799-")
                        )
    model = config.project_dir / "models/fct_orders.sql"
    before = model.read_bytes()
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "PASS", report
    assert [step["actual_rows"] for step in report["steps"]] == [0, 3, 3]
    assert report["steps"][1]["observed_mode_evidence"]["operation"] == strategy
    assert report["cleanup_status"] == "CLEANED"
    assert model.read_bytes() == before


def test_empty_incoming_snapshot_keeps_existing_target_rows(project):
    config, scenario, reports = project
    scenario.data["steps"][1]["inputs"]["orders"]["replace"]["rows"] = []
    scenario.data["steps"][1]["expect"] = {"same_as": "initial_load"}
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "PASS", report
    assert [step["actual_rows"] for step in report["steps"]] == [2, 2, 2]


def test_runtime_schema_addition_is_an_assertion_failure(project):
    config, scenario, reports = project
    model = config.project_dir / "models/fct_orders.sql"
    code = model.read_text().replace(
        "materialized='incremental'",
        "materialized='incremental', on_schema_change='append_new_columns'",
    )
    code = code.replace(
        "select order_id, event_at, updated_at, amount",
        "select order_id, event_at, updated_at, amount "
        "{% if var('add_extra', false) %}, true as extra_column{% endif %}",
    )
    model.write_text(code)
    scenario.data["steps"][1]["run"]["vars"] = {"add_extra": True}
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "FAIL", report
    assert report["steps"][0]["status"] == "PASS"
    assert report["steps"][1]["reason_code"] == "SCHEMA_MISMATCH"
    assert report["steps"][2]["status"] == "NOT_RUN"


def test_append_accepts_disjoint_new_input_batches(project):
    config, scenario, reports = project
    first_rows = copy.deepcopy(scenario.data["steps"][0]["expect"]["rows"])
    new_rows = [copy.deepcopy(scenario.data["steps"][1]["expect"]["rows"][-1])]
    scenario.data["steps"] = scenario.data["steps"][:2]
    for step in scenario.data["steps"]:
        step["run"]["vars"] = {"strategy": "append"}
    scenario.data["steps"][1]["inputs"]["orders"]["replace"]["rows"] = new_rows
    scenario.data["steps"][1]["expect"]["rows"] = first_rows + copy.deepcopy(new_rows)
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "PASS", report
    assert report["steps"][1]["observed_mode_evidence"]["operation"] == "append"


def test_compound_model_roundtrips_all_supported_types(project):
    config, scenario, reports = project
    columns = {
        "tenant_id": "integer",
        "order_id": "bigint",
        "amount": "numeric(38,2)",
        "day": "date",
        "event_at": "timestamp",
        "instant": "timestamptz",
        "updated_at": "timestamp",
        "enabled": "boolean",
        "note": "text",
    }
    initial = [
        {
            "tenant_id": tenant,
            "order_id": 1,
            "amount": "999999999999999999999999999999999999.99",
            "day": "2026-01-01",
            "event_at": "2026-01-01T00:00:00.123456",
            "instant": "2026-01-01T03:00:00+03:00",
            "updated_at": "2026-01-01T00:00:00",
            "enabled": tenant == 1,
            "note": None,
        }
        for tenant in [1, 2]
    ]
    updated = copy.deepcopy(initial)
    updated[1].update(
        amount="999999999999999999999999999999999999.98",
        note="exact é",
        updated_at="2026-01-02T00:00:00",
    )
    definition = scenario.data
    definition["inputs"]["orders"]["columns"] = copy.deepcopy(columns)
    definition["output"] = {
        "columns": copy.deepcopy(columns),
        "primary_key": ["tenant_id", "order_id"],
    }
    for step, rows in zip(definition["steps"][:2], [initial, updated], strict=True):
        step["inputs"]["orders"]["replace"]["rows"] = copy.deepcopy(rows)
        step["expect"]["rows"] = copy.deepcopy(rows)
    model = config.project_dir / "models/fct_orders.sql"
    model.write_text(
        "{{ config(materialized='incremental', unique_key=['tenant_id','order_id'], "
        "incremental_strategy='merge') }}\n"
        "select * from {{ source('raw','orders') }}\n"
        "{% if is_incremental() %}\n"
        "where updated_at >= (select max(updated_at) from {{ this }})\n"
        "{% endif %}\n"
    )
    path = config.project_dir / "scenarios/wide.yml"
    path.write_text(yaml.safe_dump(definition))
    report = run_scenario(load_scenario(path, config.project_dir), config, reports)
    assert report["overall_status"] == "PASS", report
    assert [step["actual_rows"] for step in report["steps"]] == [2, 2, 2]


def test_unchanged_ref_fixture_survives_updates_to_another_input(project):
    config, scenario, reports = project
    definition = scenario.data
    definition["inputs"]["dimensions"] = {
        "node": "model.shop.dimensions",
        "columns": {"region": "text"},
    }
    definition["steps"][0]["inputs"]["dimensions"] = {
        "replace": {"rows": [{"region": "synthetic-region"}]},
    }
    definition["output"]["columns"]["region"] = "text"
    for step in definition["steps"]:
        for row in step["expect"].get("rows", []):
            row["region"] = "synthetic-region"
    (config.project_dir / "models/dimensions.sql").write_text(
        "select * from must_not_run_upstream_sql"
    )
    model = config.project_dir / "models/fct_orders.sql"
    model.write_text(
        "{{ config(materialized='incremental', unique_key='order_id') }}\n"
        "select o.order_id,o.event_at,o.updated_at,o.amount,d.region\n"
        "from {{ source('raw','orders') }} o cross join {{ ref('dimensions') }} d\n"
        "{% if is_incremental() %}\n"
        "where o.updated_at >= (select max(updated_at) from {{ this }})\n"
        "{% endif %}\n"
    )
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "PASS", report
    assert [step["actual_rows"] for step in report["steps"]] == [2, 3, 3]


def test_unexpected_cleanup_failure_never_turns_into_pass(project, monkeypatch):
    config, scenario, reports = project
    scenario.data["steps"] = scenario.data["steps"][:1]

    def fail_cleanup(*args):
        raise ScenarioError("SIMULATED_CLEANUP_FAILURE")

    with monkeypatch.context() as context:
        context.setattr(Database, "cleanup", fail_cleanup)
        report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "ERROR", report
    assert report["steps"][0]["status"] == "PASS"
    assert report["cleanup_reason_code"] == "SIMULATED_CLEANUP_FAILURE"
    assert Journal.load(config, report["run_id"]).data["state"] == "CLEANUP_FAILED"
    cleanup_run(config, report["run_id"])


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("stale", "DBT_ARTIFACT_STALE"),
        ("mismatch", "DBT_ARTIFACT_INVOCATION_MISMATCH"),
        ("missing", "DBT_ARTIFACT_MISSING"),
        ("skipped", "DBT_MODEL_NOT_SUCCESSFUL"),
    ],
)
def test_damaged_real_dbt_results_never_pass(project, monkeypatch, fault, reason):
    config, scenario, reports = project
    original = Project.invoke
    runs = 0

    def damaged(self, command, timeout, args=()):
        nonlocal runs
        manifest, directory = original(self, command, timeout, args)
        if command == "run":
            runs += 1
            if runs == 2:
                path = directory / "target/run_results.json"
                data = json.loads(path.read_text())
                if fault == "stale":
                    data["metadata"].update(
                        generated_at="2000-01-01T00:00:00Z",
                        invocation_started_at="2000-01-01T00:00:00Z",
                    )
                elif fault == "mismatch":
                    data["metadata"]["invocation_id"] = str(uuid.uuid4())
                elif fault == "skipped":
                    data["results"][0]["status"] = "skipped"
                path.write_text(json.dumps(data))
                if fault == "missing":
                    path.unlink()
        return manifest, directory

    monkeypatch.setattr(Project, "invoke", damaged)
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "ERROR", report
    assert report["reason_code"] == reason
    assert [step["status"] for step in report["steps"]] == ["PASS", "ERROR", "NOT_RUN"]
    assert report["cleanup_status"] == "CLEANED"


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("cli_full_refresh", "EXECUTION_MODE_UNVERIFIED"),
        ("configuration", "MODEL_CONFIGURATION_CHANGED"),
        ("missing_sql", "EXECUTION_MODE_UNVERIFIED"),
        ("rebuild", "TARGET_REBUILT"),
    ],
)
def test_forced_or_unverified_incremental_mode_never_passes(project, monkeypatch, fault, reason):
    config, scenario, reports = project
    original = Project.invoke
    if fault == "configuration":
        model = config.project_dir / "models/fct_orders.sql"
        model.write_text(
            model.read_text().replace(
                "materialized='incremental'",
                "materialized='incremental', full_refresh=var('force_refresh', false)",
            )
        )
        scenario.data["steps"][1]["run"]["vars"] = {"force_refresh": True}
    runs = 0

    def changed(self, command, timeout, args=()):
        nonlocal runs
        if command == "run":
            runs += 1
            if runs == 2 and fault == "cli_full_refresh":
                args = (*args, "--full-refresh")
        manifest, directory = original(self, command, timeout, args)
        if command == "run" and runs == 2:
            node = manifest["nodes"][scenario.data["model"]]
            if fault == "missing_sql":
                (
                    directory / "target/run" / node["package_name"] / node["original_file_path"]
                ).unlink()
            elif fault == "rebuild":
                target = sql.Identifier(self.schema, node["alias"])
                saved = sql.Identifier(self.schema, "rebuilt_target")
                with psycopg.connect(**config.connection_kwargs()) as connection:
                    connection.execute(sql.SQL("CREATE TABLE {} AS TABLE {}").format(saved, target))
                    connection.execute(sql.SQL("DROP TABLE {} RESTRICT").format(target))
                    connection.execute(
                        sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                            saved, sql.Identifier(node["alias"])
                        )
                    )
        return manifest, directory

    monkeypatch.setattr(Project, "invoke", changed)
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "ERROR", report
    assert report["reason_code"] == reason
    assert report["steps"][0]["status"] == "PASS"
    assert report["steps"][2]["status"] == "NOT_RUN"
    assert report["cleanup_status"] == "CLEANED"


def test_cli_continues_independent_scenarios_and_redacts_fixture_values(project, tmp_path):
    config, scenario, reports = project
    secrets = ["synthetic.private@example.invalid", "synthetic-api-key-123456"]
    model = config.project_dir / "models/fct_orders.sql"
    model.write_text(model.read_text().replace("updated_at, amount", "updated_at, amount, note"))
    scenario.data["inputs"]["orders"]["columns"]["note"] = "text"
    scenario.data["output"]["columns"]["note"] = "text"
    for step in scenario.data["steps"]:
        for row in step.get("inputs", {}).get("orders", {}).get("replace", {}).get("rows", []):
            row["note"] = secrets[0]
        for row in step["expect"].get("rows", []):
            row["note"] = secrets[0]
    good = copy.deepcopy(scenario.data)
    good["name"] = "independent_good"
    good["steps"] = good["steps"][:1]
    bad = copy.deepcopy(scenario.data)
    bad["name"] = "first_bad"
    bad["steps"][0]["expect"]["rows"][0]["note"] = secrets[1]
    paths = []
    for name, data in [("bad", bad), ("good", good)]:
        path = config.project_dir / f"scenarios/{name}.yml"
        path.write_text(yaml.safe_dump(data))
        paths.append(path)
    result = CliRunner().invoke(
        main,
        [
            "test",
            "--config",
            str(config_file(config, tmp_path)),
            "--scenario",
            str(paths[0]),
            "--scenario",
            str(paths[1]),
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 1, result.output
    summaries = {
        report["scenario"]: report
        for path in reports.glob("*/summary.json")
        for report in [json.loads(path.read_text())]
    }
    assert summaries["independent_good"]["overall_status"] == "PASS"
    assert [step["status"] for step in summaries["first_bad"]["steps"]] == [
        "FAIL",
        "NOT_RUN",
        "NOT_RUN",
    ]
    assert all(report["cleanup_status"] == "CLEANED" for report in summaries.values())
    texts = [result.output, *(path.read_text() for path in reports.glob("*/*"))]
    assert all(
        secret not in text for secret in [*secrets, config.database["password"]] for text in texts
    )


def test_multi_input_failure_rolls_back_every_replacement(project, monkeypatch):
    config, scenario, reports = project
    scenario.data["inputs"]["dimensions"] = {
        "node": "model.shop.dimensions",
        "columns": {"region": "text"},
    }
    for index, step in enumerate(scenario.data["steps"][:2]):
        step["inputs"]["dimensions"] = {
            "replace": {"rows": [{"region": "initial" if index == 0 else "updated"}]}
        }
    (config.project_dir / "models/dimensions.sql").write_text("select * from must_not_run")
    model = config.project_dir / "models/fct_orders.sql"
    model.write_text(
        model.read_text().replace(
            "from {{ source('raw', 'orders') }}",
            "from {{ source('raw', 'orders') }} cross join {{ ref('dimensions') }}",
        )
    )
    original = Database.replace
    updates = 0

    def failing(self, schema, table, columns, rows):
        nonlocal updates
        original(self, schema, table, columns, rows)
        if table == "input_1":
            updates += 1
            if updates == 2:
                raise ScenarioError("SIMULATED_INPUT_UPDATE_FAILURE")

    monkeypatch.setattr(Database, "replace", failing)
    report = run_scenario(scenario, config, reports, keep_on_failure=True)
    journal = Journal.load(config, report["run_id"])
    try:
        assert report["overall_status"] == "ERROR", report
        assert report["reason_code"] == "SIMULATED_INPUT_UPDATE_FAILURE"
        assert report["cleanup_status"] == "KEPT"
        schema = journal.data["schemas"][1]
        with psycopg.connect(**config.connection_kwargs()) as connection:
            assert connection.execute(
                sql.SQL("SELECT region FROM {}").format(sql.Identifier(schema, "input_1"))
            ).fetchall() == [("initial",)]
            assert connection.execute(
                sql.SQL("SELECT order_id, amount::text FROM {} ORDER BY order_id").format(
                    sql.Identifier(schema, "input_0")
                )
            ).fetchall() == [(1, "10.00"), (2, "20.00")]
    finally:
        cleanup_run(config, report["run_id"])


@pytest.mark.parametrize("omit_later", [False, True])
def test_explicit_as_of_var_controls_time_for_every_step(project, omit_later):
    config, scenario, reports = project
    model = config.project_dir / "models/fct_orders.sql"
    model.write_text(
        "{% if var('as_of') is none %}"
        "{{ exceptions.raise_compiler_error('AS_OF_REQUIRED') }}{% endif %}\n"
        + model.read_text()
        .replace(
            "{% if is_incremental() %}",
            "where event_at <= '{{ var('as_of') }}'::timestamp\n{% if is_incremental() %}",
        )
        .replace("where updated_at", "and updated_at")
    )
    for step in scenario.data["steps"]:
        step["run"]["vars"] = {"as_of": "2026-01-10T00:00:00"}
        for update in step.get("inputs", {}).values():
            update["replace"]["rows"].append(
                {
                    "order_id": 999,
                    "event_at": "2027-01-01T00:00:00",
                    "updated_at": "2027-01-01T00:00:00",
                    "amount": "99.00",
                }
            )
    if omit_later:
        scenario.data["steps"][1]["run"].pop("vars")
    report = run_scenario(scenario, config, reports)
    if omit_later:
        assert report["overall_status"] == "ERROR", report
        assert report["reason_code"] == "DBT_EXECUTION_ERROR"
        assert [step["status"] for step in report["steps"]] == ["PASS", "ERROR", "NOT_RUN"]
        return
    assert report["overall_status"] == "PASS", report
    assert [step["actual_rows"] for step in report["steps"]] == [2, 3, 3]
    assert len({step["observed_mode_evidence"]["invocation_id"] for step in report["steps"]}) == 3


@pytest.mark.parametrize("style", ["direct", "nested", "macro", "later"])
def test_external_relation_is_rejected_before_model_execution(project, monkeypatch, style):
    config, scenario, reports = project
    external = "public.synthetic_sensitive_relation"
    model = config.project_dir / "models/fct_orders.sql"
    clause = f" cross join {external} forbidden"
    if style == "nested":
        clause = f" cross join (select * from {external}) forbidden"
    elif style == "macro":
        macros = config.project_dir / "macros"
        macros.mkdir(exist_ok=True)
        (macros / "external.sql").write_text(
            "{% macro external_relation() %}" + external + "{% endmacro %}"
        )
        clause = " cross join {{ external_relation() }} forbidden"
    elif style == "later":
        clause = "{% if var('external', false) %}" + clause + "{% endif %}"
        scenario.data["steps"][1]["run"]["vars"] = {"external": True}
    model.write_text(
        model.read_text().replace(
            "from {{ source('raw', 'orders') }}", "from {{ source('raw', 'orders') }}" + clause
        )
    )
    original = Project.invoke
    calls = []

    def observed(self, command, timeout, args=()):
        calls.append(command)
        return original(self, command, timeout, args)

    monkeypatch.setattr(Project, "invoke", observed)
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "ERROR", report
    assert report["reason_code"] == "SQL_EXTERNAL_RELATION"
    assert calls.count("run") == (1 if style == "later" else 0)
    assert report["cleanup_status"] == "CLEANED"
    assert "synthetic_sensitive_relation" not in json.dumps(report)


def test_table_function_is_rejected_before_model_execution(project, monkeypatch):
    config, scenario, reports = project
    model = config.project_dir / "models/fct_orders.sql"
    model.write_text(
        model.read_text().replace(
            "from {{ source('raw', 'orders') }}",
            "from {{ source('raw', 'orders') }} cross join generate_series(1,3) series",
        )
    )
    original = Project.invoke
    calls = []

    def observed(self, command, timeout, args=()):
        calls.append(command)
        return original(self, command, timeout, args)

    monkeypatch.setattr(Project, "invoke", observed)
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "ERROR", report
    assert report["reason_code"] == "SQL_AUDIT_UNSUPPORTED"
    assert "run" not in calls
    assert report["cleanup_status"] == "CLEANED"


def test_cte_model_passes_compiled_relation_audit(project):
    config, scenario, reports = project
    model = config.project_dir / "models/fct_orders.sql"
    code = model.read_text()
    config_sql, selected = code.split("select order_id", 1)
    model.write_text(
        config_sql
        + "with selected_orders as (select order_id"
        + selected
        + ") select * from SELECTED_ORDERS"
    )
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "PASS", report
    assert [step["sql_audit"]["checked_relations"] for step in report["steps"]] == [1, 2, 2]


@pytest.mark.parametrize("change", ["hook", "strategy"])
def test_later_unsupported_config_is_rejected_before_model_run(project, monkeypatch, change):
    config, scenario, reports = project
    if change == "hook":
        model = config.project_dir / "models/fct_orders.sql"
        model.write_text(
            model.read_text().replace(
                "materialized='incremental'",
                "materialized='incremental', pre_hook=var('hook_sql', [])",
            )
        )
        scenario.data["steps"][1]["run"]["vars"] = {"hook_sql": ["select 1"]}
    else:
        scenario.data["steps"][1]["run"]["vars"] = {"strategy": "unsupported_custom"}
    original = Project.invoke
    calls = []

    def observed(self, command, timeout, args=()):
        calls.append(command)
        return original(self, command, timeout, args)

    monkeypatch.setattr(Project, "invoke", observed)
    report = run_scenario(scenario, config, reports)
    assert report["overall_status"] == "ERROR", report
    assert report["reason_code"] == "MODEL_CONFIGURATION_CHANGED"
    assert calls.count("run") == 1
    assert [step["status"] for step in report["steps"]] == ["PASS", "ERROR", "NOT_RUN"]
    assert report["cleanup_status"] == "CLEANED"
