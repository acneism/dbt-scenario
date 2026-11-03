import json
import tempfile
from pathlib import Path

import click
import psycopg

from dbt_scenario import __version__
from dbt_scenario.config import load_config
from dbt_scenario.database import Database
from dbt_scenario.errors import ScenarioError, display_error
from dbt_scenario.initialize import initialize
from dbt_scenario.lifecycle import cleanup_run
from dbt_scenario.loader import load_scenario
from dbt_scenario.project import Project
from dbt_scenario.requirements import check_dependencies, project_settings
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
            click.echo(display_error(error), err=True)
        except psycopg.Error:
            click.echo(display_error(ScenarioError("DATABASE_ERROR")), err=True)
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


@main.command(help="Create a demo or scenario template without connecting to a database.")
@click.option(
    "--project-dir",
    default=".",
    type=click.Path(path_type=Path),
    help="Existing dbt project, or destination directory when using --demo.",
)
@click.option(
    "--demo", is_flag=True, help="Create a complete runnable example with synthetic data."
)
@click.option("--model", help="Incremental model name or unique_id from a manifest.")
@click.option(
    "--manifest", "manifest_path", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--catalog", "catalog_path", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option("--primary-key", multiple=True, help="Output key column; repeat for a compound key.")
@click.option(
    "--scenario-name", help="Name and filename for an additional metadata-based scenario."
)
@guarded
def init(project_dir, demo, model, manifest_path, catalog_path, primary_key, scenario_name):
    created = initialize(
        project_dir,
        demo,
        model=model,
        manifest_path=manifest_path,
        catalog_path=catalog_path,
        primary_key=primary_key,
        scenario_name=scenario_name,
    )
    for relative in created:
        click.echo(f"CREATED {relative}")
    if demo:
        click.echo("Demo ready. Set test passwords and start the disposable PostgreSQL database.")
        click.echo("Then run plan and test with examples/shop/scenarios/orders.yml.")
    elif model:
        click.echo(
            "Template created from metadata; replace every rows placeholder with a row list."
        )
        click.echo(
            "Run validate to check the edited fixtures, then configure the database and test."
        )
    else:
        click.echo(
            "Template created with synthetic data; edit model, inputs, columns and expectations."
        )
        click.echo("Then run plan --config scenario-runner.yml --scenario scenarios/example.yml.")


@main.command(help="Check scenario definitions and fixture values without database access.")
@click.option(
    "--project-dir",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Root directory containing the scenario and fixture files.",
)
@scenario_option
@guarded
def validate(project_dir, scenario_path):
    scenario = load_scenario(scenario_path, project_dir)
    click.echo(
        f"VALID definition: {len(scenario.data['inputs'])} inputs, "
        f"{len(scenario.data['steps'])} steps."
    )
    click.echo("Next: plan and test the model against the disposable database.")


@main.command(help="Check the test database role and installed project dependencies.")
@config_option
@guarded
def doctor(config_path):
    config = load_config(config_path)
    check_dependencies(config.project_dir, project_settings(config.project_dir))
    database = Database(config)
    database.close()
    click.echo("READY PostgreSQL 16; unprivileged test role; project found")


@main.command(help="Validate inputs and show the selected model, fixtures and steps.")
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
                "project_env_names": sorted(config.project_env),
            },
            indent=2,
        )
    )


@main.command("test", help="Run scenarios against the dedicated test database.")
@config_option
@click.option(
    "--scenario", "scenario_paths", multiple=True, type=click.Path(exists=True, path_type=Path)
)
@click.option("--scenario-dir", type=click.Path(exists=True, path_type=Path))
@click.option("--report-dir", default="artifacts/scenarios", type=click.Path(path_type=Path))
@click.option(
    "--keep-on-failure",
    is_flag=True,
    help="Retain failed scenario tables for debugging; successful scenarios are cleaned.",
)
@guarded
def test_command(config_path, scenario_paths, scenario_dir, report_dir, keep_on_failure):
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
        report = run_scenario(scenario, config, report_dir.resolve(), keep_on_failure)
        click.echo(f"{report['overall_status']} {report['scenario']}")
        for step in report["steps"]:
            click.echo(
                f"  {step['status']} {step['name']} {step.get('reason_code') or ''}".rstrip()
            )
        click.echo(f"  report: {report_dir / report['run_id'] / 'summary.json'}")
        if report.get("diagnostic", {}).get("hint"):
            click.echo(f"  {report['diagnostic']['hint']}")
        if report["cleanup_status"] == "KEPT":
            click.echo(f"  retained schemas; cleanup --run-id {report['run_id']}")
        status = report["overall_status"]
        exit_code = max(exit_code, {"PASS": 0, "FAIL": 1, "ERROR": 2}[status])
        if report["reason_code"] == "INTERRUPTED":
            raise click.exceptions.Exit(130)
    raise click.exceptions.Exit(exit_code)


@main.command(help="Clean database resources recorded for one inactive run.")
@config_option
@click.option("--run-id", required=True)
@guarded
def cleanup(config_path, run_id):
    result = cleanup_run(load_config(config_path, load_project_env=False), run_id)
    click.echo(f"{result} {run_id}")
