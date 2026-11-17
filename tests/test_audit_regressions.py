import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
from xml.etree import ElementTree

import pytest
import yaml

from dbt_scenario import config as scenario_config
from dbt_scenario import deadline as scenario_deadline
from dbt_scenario import errors, loader, process, requirements, runner
from dbt_scenario import project as scenario_project
from dbt_scenario import report as scenario_report

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "setting", ["sql_header", "incremental_predicates", "predicates"]
)
def test_unexamined_model_sql_is_refused_in_preflight_and_later_steps(setting):
    config = {
        "materialized": "incremental",
        setting: ["select 1 from pg_catalog.pg_class"],
    }
    with pytest.raises(
        errors.ScenarioError, match="MODEL_SQL_CONFIG_UNSUPPORTED"
    ):
        requirements.check_model_config(config)
    node = {
        "unique_id": "model.shop.fct_orders",
        "alias": "fct_orders",
        "schema": "isolated",
        "database": "disposable",
        "config": {"materialized": "incremental"},
    }
    changed = copy.deepcopy(node)
    changed["config"] = config
    with pytest.raises(
        errors.ScenarioError, match="MODEL_CONFIGURATION_CHANGED"
    ):
        runner.execution_node(
            {"nodes": {node["unique_id"]: changed}},
            node,
            "isolated",
            "disposable",
        )


def test_empty_sql_configuration_remains_supported():
    requirements.check_model_config(
        {
            "materialized": "incremental",
            "sql_header": "",
            "incremental_predicates": [],
        }
    )


def test_project_fingerprint_frames_path_and_content(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for root in [first, second]:
        (root / "models").mkdir(parents=True)
        (root / "dbt_project.yml").write_text(
            "name: collision\nconfig-version: 2\n"
        )
    (first / "models/a.sql").write_text(
        "select 1 as id\n-- models/b.sqlselect 2 as id\n"
    )
    (second / "models/a.sql").write_text("select 1 as id\n-- ")
    (second / "models/b.sql").write_text("select 2 as id\n")
    assert scenario_project.fingerprint(first) != scenario_project.fingerprint(
        second
    )


def test_project_uses_the_copied_sql_and_settings_for_its_fingerprint(
    tmp_path, monkeypatch
):
    source = tmp_path / "shop"
    shutil.copytree(ROOT / "examples/shop", source)
    model = source / "models/fct_orders.sql"
    settings = source / "dbt_project.yml"
    original_hash = scenario_project.fingerprint(source)
    original_copy = shutil.copytree

    def update_before_copy(project_dir, destination, *args, **options):
        if pathlib.Path(project_dir) == source:
            model.write_text("select 2 as id\n", encoding="utf-8")
            with settings.open("a", encoding="utf-8") as stream:
                stream.write("\nvars:\n  copy_marker: staged\n")
        return original_copy(project_dir, destination, *args, **options)

    monkeypatch.setattr(shutil, "copytree", update_before_copy)
    config = scenario_config.Config(
        source,
        {
            "host": "unused",
            "port": 1,
            "dbname": "unused",
            "user": "unused",
            "password": "unused",
        },
    )
    project = scenario_project.Project(
        config, tmp_path / "workspace", "isolated"
    )

    assert project.project_hash != original_hash
    assert project.project_hash == scenario_project.fingerprint(source)
    assert (
        project.root / model.relative_to(source)
    ).read_bytes() == model.read_bytes()
    assert project.settings["vars"]["copy_marker"] == "staged"


@pytest.mark.parametrize("excluded", [".venv", ".git", "target", "logs"])
def test_excluded_directory_symlink_is_not_scanned_or_copied(
    tmp_path, monkeypatch, excluded
):
    project = tmp_path / "shop"
    shutil.copytree(ROOT / "examples/shop", project)
    link = project / excluded / "bin/python"
    link.parent.mkdir(parents=True)
    link.write_text("excluded environment file")
    original = pathlib.Path.is_symlink
    monkeypatch.setattr(
        pathlib.Path, "is_symlink", lambda path: path == link or original(path)
    )
    config = scenario_config.Config(
        project,
        {
            "host": "unused",
            "port": 1,
            "dbname": "unused",
            "user": "unused",
            "password": "unused",
        },
    )
    before = scenario_project.fingerprint(project)
    copied = scenario_project.Project(
        config, tmp_path / "workspace", "isolated"
    )
    assert not (copied.root / excluded).exists()
    assert scenario_project.fingerprint(project) == before


def test_real_venv_symlink_is_excluded_but_model_symlink_is_refused(tmp_path):
    project = tmp_path / "project"
    (project / ".venv/bin").mkdir(parents=True)
    (project / "models").mkdir()
    (project / "dbt_project.yml").write_text("name: audit\nconfig-version: 2\n")
    try:
        (project / ".venv/bin/python").symlink_to(sys.executable)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    config = scenario_config.Config(
        project,
        {
            "host": "unused",
            "port": 1,
            "dbname": "unused",
            "user": "unused",
            "password": "unused",
        },
    )
    copied = scenario_project.Project(config, tmp_path / "accepted", "isolated")
    assert not (copied.root / ".venv").exists()
    (project / "models/external.sql").symlink_to(project / "dbt_project.yml")
    with pytest.raises(
        errors.ScenarioError, match="PROJECT_SYMLINK_UNSUPPORTED"
    ):
        scenario_project.Project(config, tmp_path / "refused", "isolated")


@pytest.mark.parametrize(
    ("status", "cleanup", "step_status", "exit_code", "valid"),
    [
        ("PASS", "CLEANED", "PASS", 0, True),
        ("FAIL", "CLEANED", "FAIL", 1, True),
        ("ERROR", "NOT_NEEDED", "NOT_RUN", 2, True),
        ("ERROR", "ERROR", "PASS", 2, True),
        ("ERROR", "CLEANED", "ERROR", 2, True),
        ("ERROR", "KEPT", "ERROR", 2, True),
        ("PASS", "CLEANED", "PASS", 0, False),
    ],
)
def test_workflow_accepts_versioned_reports_and_preserves_results(
    tmp_path, status, cleanup, step_status, exit_code, valid
):
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/scenarios.yml").read_text()
    )
    step = next(
        item
        for item in workflow["jobs"]["scenarios"]["steps"]
        if item.get("name") == "Summarize scenario results"
    )
    code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    directory = tmp_path / "reports" / ("a" * 32)
    directory.mkdir(parents=True)
    project = ROOT / "examples/shop"
    scenario = loader.load_scenario(project / "scenarios/orders.yml", project)
    report = runner.initialize_report(
        scenario, scenario_config.Config(project, {}), directory.name
    )
    report.update(
        overall_status=status,
        cleanup_status=cleanup,
        reason_code="SCENARIO_FAILURE" if status == "ERROR" else None,
        steps=[
            {
                "name": "initial",
                "status": step_status,
                "duration_ms": 50,
                "reason_code": "STEP_FAILURE"
                if step_status in {"ERROR", "FAIL"}
                else None,
            }
        ],
    )
    scenario_report.write_report(report, directory)
    report_path = directory / "summary.json"
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    junit = ElementTree.parse(directory / "junit.xml").getroot()
    assert junit.get("failures") == str(int(status == "FAIL"))
    assert junit.get("errors") == str(int(status == "ERROR"))
    if not valid:
        report_path.write_text(
            json.dumps({**report, "schema_version": 2}), encoding="utf-8"
        )
    summary = tmp_path / "github-summary"
    environment = dict(
        os.environ,
        DSC_CI_ROOT=str(tmp_path),
        DSC_CI_TEST_OUTCOME="failure" if exit_code else "success",
        DSC_CI_TEST_EXIT=str(exit_code),
        GITHUB_STEP_SUMMARY=str(summary),
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        env=environment,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == (0 if valid else 1), result.stderr
    aggregate = json.loads((tmp_path / "reports/ci-summary.json").read_text())
    assert aggregate["statuses"] == ({status: 1} if valid else {})
    assert aggregate["cleanup_statuses"] == ({cleanup: 1} if valid else {})
    assert aggregate["summaries_valid"] is valid
    assert aggregate["all_passed_and_cleaned"] is (valid and not exit_code)
    assert aggregate["test_exit_code"] == exit_code


def test_unexpected_setup_error_reports_a_safe_stage(tmp_path, monkeypatch):
    project = ROOT / "examples/shop"
    scenario = loader.load_scenario(project / "scenarios/orders.yml", project)

    def fail_to_connect(config, deadline):
        raise RuntimeError("private internal details")

    monkeypatch.setattr("dbt_scenario.database.Database", fail_to_connect)
    report = runner.run_scenario(
        scenario, scenario_config.Config(project, {}), tmp_path
    )

    assert report["overall_status"] == "ERROR"
    assert report["reason_code"] == "INTERNAL_ERROR"
    assert report["error_stage"] == "setup"
    assert all(step["status"] == "NOT_RUN" for step in report["steps"])
    for filename in ["summary.json", "summary.md", "junit.xml"]:
        path = tmp_path / report["run_id"] / filename
        assert "private internal details" not in path.read_text(
            encoding="utf-8"
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object semantics")
@pytest.mark.parametrize("parent_waits", [False, True])
def test_windows_timeout_terminates_descendants_even_after_parent_exit(
    tmp_path, parent_waits
):
    pid_path = tmp_path / "child.pid"
    marker = tmp_path / "survived"
    child = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pid_path)!r}).write_text(str(os.getpid())); "
        f"time.sleep(3); Path({str(marker)!r}).write_text('survived'); "
        "time.sleep(30)"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
    )
    parent += "time.sleep(30)" if parent_waits else "time.sleep(0.1)"
    with pytest.raises(errors.ScenarioError, match="STEP_TIMEOUT"):
        process.run_process(
            [sys.executable, "-c", parent],
            dict(os.environ),
            tmp_path,
            scenario_deadline.Deadline(1.5, "STEP_TIMEOUT"),
        )
    assert pid_path.exists()
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.OpenProcess(0x100000, False, int(pid_path.read_text()))
    if handle:
        try:
            assert api.WaitForSingleObject(handle, 2000) == 0
        finally:
            api.CloseHandle(handle)
    assert not marker.exists()


def test_process_exit_code_is_preserved(tmp_path):
    assert (
        process.run_process(
            [sys.executable, "-c", "raise SystemExit(7)"],
            dict(os.environ),
            tmp_path,
            scenario_deadline.Deadline(10, "STEP_TIMEOUT"),
        )
        == 7
    )
