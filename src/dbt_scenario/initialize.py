import contextlib
from importlib.resources import files
from pathlib import Path

import yaml

from dbt_scenario.errors import ScenarioError
from dbt_scenario.requirements import project_settings


def template_files(directory, prefix="") -> dict[str, str]:
    result = {}
    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        relative = f"{prefix}{child.name}"
        if child.is_dir():
            result.update(template_files(child, f"{relative}/"))
        else:
            result[relative] = child.read_text(encoding="utf-8")
    return result


def write_new_files(root: Path, contents: dict[str, str]):
    if root.is_symlink():
        raise ScenarioError("INIT_UNSAFE_PATH")
    root = root.resolve()
    destinations = []
    for relative, text in contents.items():
        path = root / relative
        if not path.resolve().is_relative_to(root):
            raise ScenarioError("INIT_UNSAFE_PATH")
        for parent in [path, *path.parents]:
            if parent == root.parent:
                break
            if parent.is_symlink() or (parent.exists() and parent != path and not parent.is_dir()):
                raise ScenarioError("INIT_UNSAFE_PATH")
        if path.exists():
            raise ScenarioError("INIT_WOULD_OVERWRITE")
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


def initialize(project_dir: Path, demo: bool = False) -> list[str]:
    templates = files("dbt_scenario").joinpath("templates", "demo")
    contents = template_files(templates)
    if demo:
        return write_new_files(project_dir, contents)
    settings = project_settings(project_dir)
    scenario_root = templates.joinpath("examples", "shop", "scenarios")
    scenario = yaml.safe_load(scenario_root.joinpath("orders.yml").read_text())
    scenario["name"] = "example_incremental_scenario"
    scenario["model"] = f"model.{settings['name']}.replace_with_your_model"
    scenario["inputs"]["orders"]["node"] = (
        f"source.{settings['name']}.replace_with_your_source.replace_with_your_table"
    )
    for step in scenario["steps"]:
        fixture_definitions = [update["replace"] for update in step.get("inputs", {}).values()]
        fixture_definitions.append(step["expect"])
        for fixture in fixture_definitions:
            if "fixture" in fixture:
                payload = yaml.safe_load(scenario_root.joinpath(fixture.pop("fixture")).read_text())
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
