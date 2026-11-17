import contextlib
import pathlib
import re
from collections.abc import Sequence
from importlib import resources
from importlib.resources import abc as resource_abc

import yaml

from dbt_scenario import errors, requirements, scaffold


def template_files(
    directory: resource_abc.Traversable, prefix: str = ""
) -> dict[str, str]:
    result = {}
    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        relative = f"{prefix}{child.name}"
        if child.is_dir():
            result.update(template_files(child, f"{relative}/"))
        else:
            result[relative] = child.read_text(encoding="utf-8")
    return result


def write_new_files(root: pathlib.Path, contents: dict[str, str]) -> list[str]:
    if root.is_symlink():
        raise errors.ScenarioError("INIT_UNSAFE_PATH")
    root = root.resolve()
    destinations = []
    for relative, text in contents.items():
        path = root / relative
        if not path.resolve().is_relative_to(root):
            raise errors.ScenarioError("INIT_UNSAFE_PATH")
        for parent in [path, *path.parents]:
            if parent == root.parent:
                break
            if parent.is_symlink() or (
                parent.exists() and parent != path and not parent.is_dir()
            ):
                raise errors.ScenarioError("INIT_UNSAFE_PATH")
        if path.exists():
            raise errors.ScenarioError("INIT_WOULD_OVERWRITE")
        destinations.append((path, text))
    created_files = []
    created_directories = []
    try:
        for path, text in destinations:
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_directories.append(directory)
            with path.open("x", encoding="utf-8", newline="\n") as output:
                created_files.append(path)
                output.write(text)
            if path.suffix == ".sh":
                path.chmod(0o755)
    except BaseException:
        for path in reversed(created_files):
            path.unlink(missing_ok=True)
        for directory in reversed(created_directories):
            with contextlib.suppress(OSError):
                directory.rmdir()
        raise
    return [path.relative_to(root).as_posix() for path, _ in destinations]


def initialize(
    project_dir: pathlib.Path,
    demo: bool = False,
    *,
    model: str | None = None,
    manifest_path: pathlib.Path | None = None,
    catalog_path: pathlib.Path | None = None,
    primary_key: Sequence[str] = (),
    scenario_name: str | None = None,
) -> list[str]:
    if (
        (
            demo
            and (
                model
                or manifest_path
                or catalog_path
                or primary_key
                or scenario_name
            )
        )
        or (bool(model) != bool(manifest_path))
        or (
            (catalog_path or primary_key or scenario_name is not None)
            and not model
        )
    ):
        raise errors.ScenarioError("INIT_OPTIONS_INVALID")
    templates = resources.files("dbt_scenario").joinpath("templates", "demo")
    contents = template_files(templates)
    if demo:
        return write_new_files(project_dir, contents)
    settings = requirements.project_settings(project_dir)
    if model:
        name, scenario = scaffold.scaffold(
            settings, model, manifest_path, catalog_path, primary_key
        )
        if scenario_name is not None:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", scenario_name):
                raise errors.ScenarioError("INIT_SCENARIO_NAME_INVALID")
            name = scenario_name
            scenario["name"] = scenario_name
        generated = {
            scaffold.scenario_filename(name): yaml.safe_dump(
                scenario, sort_keys=False
            )
        }
        config_path = project_dir / "scenario-runner.yml"
        if not config_path.exists():
            config = yaml.safe_load(contents["scenario-runner.yml"])
            config["project_dir"] = "."
            generated = {
                "scenario-runner.yml": yaml.safe_dump(config, sort_keys=False),
                **generated,
            }
        elif not config_path.is_file():
            raise errors.ScenarioError("INIT_WOULD_OVERWRITE")
        return write_new_files(project_dir, generated)
    scenario_root = templates.joinpath("examples", "shop", "scenarios")
    scenario = yaml.safe_load(scenario_root.joinpath("orders.yml").read_text())
    scenario["name"] = "example_incremental_scenario"
    scenario["model"] = f"model.{settings['name']}.replace_with_your_model"
    scenario["inputs"]["orders"]["node"] = (
        f"source.{settings['name']}."
        "replace_with_your_source.replace_with_your_table"
    )
    for step in scenario["steps"]:
        fixture_definitions = [
            update["replace"] for update in step.get("inputs", {}).values()
        ]
        fixture_definitions.append(step["expect"])
        for fixture in fixture_definitions:
            if "fixture" in fixture:
                payload = yaml.safe_load(
                    scenario_root.joinpath(fixture.pop("fixture")).read_text()
                )
                fixture["rows"] = payload["rows"]
    config = yaml.safe_load(contents["scenario-runner.yml"])
    config["project_dir"] = "."
    return write_new_files(
        project_dir,
        {
            "scenario-runner.yml": yaml.safe_dump(config, sort_keys=False),
            "scenarios/example.yml": yaml.safe_dump(scenario, sort_keys=False),
        },
    )
