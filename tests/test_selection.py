import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from dbt_scenario.cli import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def selection(tmp_path, monkeypatch):
    project = tmp_path / "shop"
    shutil.copytree(ROOT / "examples/shop", project, ignore=shutil.ignore_patterns(".dbt-scenario"))
    config = tmp_path / "scenario-runner.yml"
    config.write_text("configuration is supplied by the selection test")
    monkeypatch.setattr(
        "dbt_scenario.cli.load_config", lambda path: SimpleNamespace(project_dir=project)
    )
    executed = []

    def run(scenario, config, report_dir, keep_on_failure):
        executed.append(scenario.path)
        return {
            "overall_status": "PASS",
            "scenario": scenario.data["name"],
            "steps": [],
            "run_id": str(len(executed)),
            "cleanup_status": "CLEANED",
            "reason_code": None,
        }

    monkeypatch.setattr("dbt_scenario.cli.run_scenario", run)
    return project, config, executed


def test_file_passed_as_scenario_directory_never_runs_other_selected_scenarios(selection):
    project, config, executed = selection
    result = CliRunner().invoke(
        main,
        [
            "test",
            "--config",
            str(config),
            "--scenario",
            str(project / "scenarios/orders.yml"),
            "--scenario-dir",
            str(project / "scenarios/empty-start.yml"),
        ],
    )
    assert result.exit_code == 2, result.output
    assert "--scenario-dir" in result.output
    assert not executed


def test_mixed_selection_deduplicates_paths_and_keeps_fixture_subdirectories_out(selection):
    project, config, executed = selection
    scenarios = project / "scenarios"
    extra = scenarios / "extra.yaml"
    extra.write_bytes((scenarios / "orders.yml").read_bytes())
    result = CliRunner().invoke(
        main,
        [
            "test",
            "--config",
            str(config),
            "--scenario",
            str(scenarios / "orders.yml"),
            "--scenario",
            str(scenarios / "../scenarios/orders.yml"),
            "--scenario-dir",
            str(scenarios),
        ],
    )
    assert result.exit_code == 0, result.output
    assert executed == [
        (scenarios / "orders.yml").resolve(),
        (scenarios / "empty-start.yml").resolve(),
        extra.resolve(),
    ]


@pytest.mark.parametrize("command", ["test", "plan", "validate"])
def test_directory_cannot_be_supplied_as_a_scenario_file(selection, monkeypatch, command):
    project, config, executed = selection
    monkeypatch.setattr(
        "dbt_scenario.cli.load_config", lambda *a: pytest.fail("configuration was loaded")
    )
    arguments = [command, "--scenario", str(project / "scenarios")]
    if command == "validate":
        arguments.extend(["--project-dir", str(project)])
    else:
        arguments.extend(["--config", str(config)])
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 2, result.output
    assert "--scenario" in result.output
    assert not executed


def test_directory_cannot_be_supplied_as_a_configuration_file(selection, monkeypatch):
    project, _, executed = selection
    monkeypatch.setattr(
        "dbt_scenario.cli.load_config", lambda *a: pytest.fail("configuration was loaded")
    )
    result = CliRunner().invoke(main, ["doctor", "--config", str(project)])
    assert result.exit_code == 2, result.output
    assert "--config" in result.output
    assert not executed
