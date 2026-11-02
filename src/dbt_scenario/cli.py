import json
import tempfile
from pathlib import Path

import click
import psycopg

from dbt_scenario import __version__
from dbt_scenario.config import load_config
from dbt_scenario.database import Database
from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import load_scenario
from dbt_scenario.project import Project
from dbt_scenario.runner import run_scenario


@click.group()
@click.version_option(__version__)
def main():
    pass


def guarded(function):
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ScenarioError as error:
            click.echo(f"ERROR {error.code}", err=True)
        except psycopg.Error:
            click.echo("ERROR DATABASE_ERROR", err=True)
        except (OSError, ValueError, TypeError):
            click.echo("ERROR INVALID_INPUT_OR_ENVIRONMENT", err=True)
        raise click.exceptions.Exit(2)

    wrapped.__name__ = function.__name__
    return wrapped


config_option = click.option(
    "--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path)
)
scenario_option = click.option(
    "--scenario", "scenario_path", required=True, type=click.Path(exists=True, path_type=Path)
)


@main.command()
@config_option
@guarded
def doctor(config_path):
    config = load_config(config_path)
    database = Database(config)
    database.close()
    click.echo("READY PostgreSQL 16; unprivileged test role; project found")


@main.command()
@config_option
@scenario_option
@guarded
def plan(config_path, scenario_path):
    config = load_config(config_path)
    scenario = load_scenario(scenario_path, config.project_dir)
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-plan-") as temporary:
        project = Project(config, Path(temporary), "dsc_plan")
        node = project.inspect(scenario.data, config.step_timeout)
    click.echo(
        json.dumps(
            {
                "scenario": scenario.data["name"],
                "model": node["unique_id"],
                "inputs": list(scenario.data["inputs"]),
                "steps": [s["name"] for s in scenario.data["steps"]],
            },
            indent=2,
        )
    )


@main.command("test")
@config_option
@click.option(
    "--scenario", "scenario_paths", multiple=True, type=click.Path(exists=True, path_type=Path)
)
@click.option("--scenario-dir", type=click.Path(exists=True, path_type=Path))
@click.option("--report-dir", default="artifacts/scenarios", type=click.Path(path_type=Path))
@guarded
def test_command(config_path, scenario_paths, scenario_dir, report_dir):
    config = load_config(config_path)
    paths = list(scenario_paths)
    if scenario_dir:
        paths.extend(sorted(scenario_dir.glob("*.yml")))
        paths.extend(sorted(scenario_dir.glob("*.yaml")))
    paths = list(dict.fromkeys(path.resolve() for path in paths))
    if not paths:
        raise ScenarioError("NO_SCENARIOS_SELECTED")
    scenarios = [load_scenario(path, config.project_dir) for path in paths]
    exit_code = 0
    for scenario in scenarios:
        report = run_scenario(scenario, config, report_dir.resolve())
        click.echo(f"{report['overall_status']} {report['scenario']}")
        for step in report["steps"]:
            click.echo(
                f"  {step['status']} {step['name']} {step.get('reason_code') or ''}".rstrip()
            )
        click.echo(f"  report: {report_dir / report['run_id'] / 'summary.json'}")
        status = report["overall_status"]
        exit_code = max(exit_code, {"PASS": 0, "FAIL": 1, "ERROR": 2}[status])
        if report["reason_code"] == "INTERRUPTED":
            raise click.exceptions.Exit(130)
    raise click.exceptions.Exit(exit_code)
