import json
import pathlib
import tempfile
from collections.abc import Callable

import click
import psycopg

import dbt_scenario
from dbt_scenario import config as scenario_config
from dbt_scenario import database as scenario_database
from dbt_scenario import (
    discovery,
    errors,
    initialize,
    lifecycle,
    loader,
    requirements,
    runner,
)
from dbt_scenario import project as scenario_project
from dbt_scenario import report as scenario_report


@click.group()
@click.version_option(dbt_scenario.__version__)
def main() -> None:
    pass


def guarded[**P](function: Callable[P, None]) -> Callable[P, None]:
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            return function(*args, **kwargs)
        except errors.ScenarioError as error:
            click.echo(errors.display_error(error), err=True)
        except psycopg.Error:
            click.echo(
                errors.display_error(errors.ScenarioError("DATABASE_ERROR")),
                err=True,
            )
        except (OSError, ValueError, TypeError):
            click.echo("ERROR INVALID_INPUT_OR_ENVIRONMENT", err=True)
        raise click.exceptions.Exit(2)

    wrapped.__name__ = function.__name__
    return wrapped


config_option = click.option(
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
)
scenario_option = click.option(
    "--scenario",
    "scenario_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
)


@main.command(
    help="Create a demo or scenario template without connecting to a database."
)
@click.option(
    "--project-dir",
    default=".",
    type=click.Path(path_type=pathlib.Path),
    help="Existing dbt project, or destination directory when using --demo.",
)
@click.option(
    "--demo",
    is_flag=True,
    help="Create a complete runnable example with synthetic data.",
)
@click.option(
    "--model", help="Incremental model name or unique_id from a manifest."
)
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
)
@click.option(
    "--primary-key",
    multiple=True,
    help="Output key column; repeat for a compound key.",
)
@click.option(
    "--scenario-name",
    help="Name and filename for an additional metadata-based scenario.",
)
@guarded
def init(
    project_dir: pathlib.Path,
    demo: bool,
    model: str | None,
    manifest_path: pathlib.Path | None,
    catalog_path: pathlib.Path | None,
    primary_key: tuple[str, ...],
    scenario_name: str | None,
) -> None:
    created = initialize.initialize(
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
        click.echo(
            "Demo ready. Set test passwords and start the disposable "
            "PostgreSQL database."
        )
        click.echo(
            "Then run plan and test with examples/shop/scenarios/orders.yml."
        )
    elif model:
        click.echo(
            "Template created from metadata; replace every rows placeholder "
            "with a row list."
        )
        click.echo(
            "Run validate to check the edited fixtures, then configure the "
            "database and test."
        )
    else:
        click.echo(
            "Template created with synthetic data; edit model, inputs, columns "
            "and expectations."
        )
        click.echo(
            "Then run plan --config scenario-runner.yml --scenario "
            "scenarios/example.yml."
        )


@main.command(
    help=(
        "List incremental models and metadata blockers without database access."
    )
)
@click.option(
    "--project-dir",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=pathlib.Path),
)
@click.option(
    "--manifest",
    "manifest_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
)
@guarded
def discover(
    project_dir: pathlib.Path,
    manifest_path: pathlib.Path,
    catalog_path: pathlib.Path | None,
) -> None:
    click.echo(
        json.dumps(
            discovery.discover_models(project_dir, manifest_path, catalog_path),
            indent=2,
        )
    )


@main.command(
    help=(
        "Check scenario definitions and fixture values without database access."
    )
)
@click.option(
    "--project-dir",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=pathlib.Path),
    help="Root directory containing the scenario and fixture files.",
)
@scenario_option
@guarded
def validate(project_dir: pathlib.Path, scenario_path: pathlib.Path) -> None:
    scenario = loader.load_scenario(scenario_path, project_dir)
    click.echo(
        f"VALID definition: {len(scenario.data['inputs'])} inputs, "
        f"{len(scenario.data['steps'])} steps."
    )
    click.echo("Next: plan and test the model against the disposable database.")


@main.command(
    help="Check the test database role and installed project dependencies."
)
@config_option
@guarded
def doctor(config_path: pathlib.Path) -> None:
    config = scenario_config.load_config(config_path)
    requirements.check_dependencies(
        config.project_dir, requirements.project_settings(config.project_dir)
    )
    database = scenario_database.Database(config)
    database.close()
    click.echo("READY PostgreSQL 16; unprivileged test role; project found")


@main.command(
    help="Validate inputs and show the selected model, fixtures and steps."
)
@config_option
@scenario_option
@guarded
def plan(config_path: pathlib.Path, scenario_path: pathlib.Path) -> None:
    config = scenario_config.load_config(config_path)
    scenario = loader.load_scenario(scenario_path, config.project_dir)
    with tempfile.TemporaryDirectory(prefix="dbt-scenario-plan-") as temporary:
        project = scenario_project.Project(
            config, pathlib.Path(temporary), "dsc_plan"
        )
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
    "--scenario",
    "scenario_paths",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
)
@click.option(
    "--scenario-dir",
    type=click.Path(exists=True, file_okay=False, path_type=pathlib.Path),
)
@click.option(
    "--report-dir",
    default="artifacts/scenarios",
    type=click.Path(path_type=pathlib.Path),
)
@click.option(
    "--keep-on-failure",
    is_flag=True,
    help=(
        "Retain failed scenario tables for debugging; successful scenarios are "
        "cleaned."
    ),
)
@guarded
def test_command(
    config_path: pathlib.Path,
    scenario_paths: tuple[pathlib.Path, ...],
    scenario_dir: pathlib.Path | None,
    report_dir: pathlib.Path,
    keep_on_failure: bool,
) -> None:
    config = scenario_config.load_config(config_path)
    paths = list(scenario_paths)
    if scenario_dir:
        paths.extend(sorted(scenario_dir.glob("*.yml")))
        paths.extend(sorted(scenario_dir.glob("*.yaml")))
    paths = list(dict.fromkeys(path.resolve() for path in paths))
    if not paths:
        raise errors.ScenarioError("NO_SCENARIOS_SELECTED")
    scenarios = [
        loader.load_scenario(path, config.project_dir) for path in paths
    ]
    exit_code = 0
    for scenario in scenarios:
        report = runner.run_scenario(
            scenario, config, report_dir.resolve(), keep_on_failure
        )
        click.echo(f"{report['overall_status']} {report['scenario']}")
        for line in scenario_report.reason_lines(report):
            click.echo(f"  {line}")
        for step in report["steps"]:
            click.echo(
                (
                    f"  {step['status']} {step['name']} "
                    f"{step.get('reason_code') or ''}"
                ).rstrip()
            )
        click.echo(
            f"  report: {report_dir / report['run_id'] / 'summary.json'}"
        )
        if report.get("diagnostic", {}).get("hint"):
            click.echo(f"  {report['diagnostic']['hint']}")
        if report["cleanup_status"] == "KEPT":
            click.echo(
                f"  retained schemas; cleanup --run-id {report['run_id']}"
            )
        status = report["overall_status"]
        exit_code = max(exit_code, {"PASS": 0, "FAIL": 1, "ERROR": 2}[status])
        if report["reason_code"] == "INTERRUPTED":
            raise click.exceptions.Exit(130)
    raise click.exceptions.Exit(exit_code)


@main.command(help="Clean database resources recorded for one inactive run.")
@config_option
@click.option("--run-id", required=True)
@guarded
def cleanup(config_path: pathlib.Path, run_id: str) -> None:
    result = lifecycle.cleanup_run(
        scenario_config.load_config(config_path, load_project_env=False), run_id
    )
    click.echo(f"{result} {run_id}")
