import copy
import uuid
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from dbt_scenario.cli import main
from dbt_scenario.config import load_config
from dbt_scenario.environment import process_environment
from dbt_scenario.errors import ScenarioError, display_error
from dbt_scenario.initialize import initialize
from dbt_scenario.journal import Journal
from dbt_scenario.loader import load_scenario
from dbt_scenario.requirements import check_dependencies, project_settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def existing_project(tmp_path):
    (tmp_path / "dbt_project.yml").write_text("name: analytics\nconfig-version: 2\n")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "untouched.sql").write_text("select 1 as id\n")
    return tmp_path


def example_config(project):
    document = yaml.safe_load((ROOT / "scenario-runner.yml").read_text())
    document["project_dir"] = str(project)
    return document


def save_config(project, document):
    path = project / "test-runner.yml"
    path.write_text(yaml.safe_dump(document))
    return path


def test_demo_initializes_without_passwords_or_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DSC_TEST_PASSWORD", raising=False)
    target = tmp_path / "demo"
    result = CliRunner().invoke(main, ["init", "--demo", "--project-dir", str(target)])
    assert result.exit_code == 0, result.output
    scenario = load_scenario(
        target / "examples/shop/scenarios/orders.yml", target / "examples/shop"
    )
    assert len(scenario.data["steps"]) == 3
    assert (target / "compose.yml").is_file()
    assert (target / "scripts/init-test-db.sh").is_file()
    assert not (target / ".dbt-scenario").exists()


def test_initializing_existing_project_keeps_model_sql(existing_project):
    before = (existing_project / "models" / "untouched.sql").read_bytes()
    created = initialize(existing_project)
    assert created == ["scenario-runner.yml", "scenarios/example.yml"]
    scenario = load_scenario(existing_project / "scenarios/example.yml", existing_project)
    assert scenario.data["model"] == "model.analytics.replace_with_your_model"
    assert (existing_project / "models" / "untouched.sql").read_bytes() == before
    assert (
        yaml.safe_load((existing_project / "scenario-runner.yml").read_text())["project_dir"] == "."
    )


def test_init_never_overwrites_an_existing_destination(tmp_path):
    initialize(tmp_path / "demo", demo=True)
    sentinel = tmp_path / "demo/examples/shop/models/fct_orders.sql"
    sentinel.write_text("user edit must survive")
    with pytest.raises(ScenarioError, match="INIT_WOULD_OVERWRITE"):
        initialize(tmp_path / "demo", demo=True)
    assert sentinel.read_text() == "user edit must survive"


def test_init_checks_all_collisions_before_writing(existing_project):
    directory = existing_project / "scenarios"
    directory.mkdir()
    (directory / "example.yml").write_text("user scenario")
    with pytest.raises(ScenarioError, match="INIT_WOULD_OVERWRITE"):
        initialize(existing_project)
    assert not (existing_project / "scenario-runner.yml").exists()
    assert (directory / "example.yml").read_text() == "user scenario"


def test_init_rolls_back_files_created_before_an_io_error(existing_project, monkeypatch):
    original = Path.open

    def fail_second_file(path, mode="r", *args, **kwargs):
        if path.name == "example.yml" and mode == "x":
            raise OSError("simulated disk error")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second_file)
    with pytest.raises(OSError):
        initialize(existing_project)
    assert not (existing_project / "scenario-runner.yml").exists()
    assert not (existing_project / "scenarios").exists()
    assert (existing_project / "models/untouched.sql").read_text() == "select 1 as id\n"


def test_init_rejects_symlinked_output(existing_project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (existing_project / "scenarios").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ScenarioError, match="INIT_UNSAFE_PATH"):
        initialize(existing_project)
    assert not (outside / "example.yml").exists()


@pytest.mark.parametrize(
    "name",
    [
        "PATH",
        "HOME",
        "PGHOST",
        "PGOPTIONS",
        "PYTHONPATH",
        "LD_PRELOAD",
        "DBT_TARGET",
        "DBT_SEND_ANONYMOUS_USAGE_STATS",
        "DBT_ENV_SECRET_DSC_PASSWORD",
        "OPENSSL_CONF",
        "bad-name",
    ],
)
def test_config_rejects_runtime_control_variables(existing_project, monkeypatch, name):
    monkeypatch.setenv("DSC_TEST_PASSWORD", "test-only-password")
    document = example_config(existing_project)
    document["env_allowlist"] = [name]
    with pytest.raises(ScenarioError, match="INVALID_ENV_ALLOWLIST"):
        load_config(save_config(existing_project, document))


def test_environment_only_forwards_explicit_project_variables(existing_project, monkeypatch):
    monkeypatch.setenv("DSC_TEST_PASSWORD", "private-db-password")
    monkeypatch.setenv("PROJECT_REGION", "synthetic-region-value")
    monkeypatch.setenv("UNLISTED_PRIVATE_VALUE", "never-forward-me")
    document = example_config(existing_project)
    document["env_allowlist"] = ["PROJECT_REGION"]
    config = load_config(save_config(existing_project, document))
    environment = process_environment(config.project_env, config.database["password"])
    assert environment["PROJECT_REGION"] == "synthetic-region-value"
    assert "UNLISTED_PRIVATE_VALUE" not in environment
    assert "DSC_TEST_PASSWORD" not in environment
    assert environment["DBT_ENV_SECRET_DSC_PASSWORD"] == "private-db-password"
    assert "synthetic-region-value" not in repr(config)
    assert "private-db-password" not in repr(config)


@pytest.mark.parametrize(
    "names",
    [
        ["PROJECT_REGION", "project_region"],
        ["DSC_TEST_PASSWORD"],
        "PROJECT_REGION",
        [None],
    ],
)
def test_config_rejects_ambiguous_allowlists(existing_project, monkeypatch, names):
    monkeypatch.setenv("DSC_TEST_PASSWORD", "test-only-password")
    document = example_config(existing_project)
    document["env_allowlist"] = names
    with pytest.raises(ScenarioError, match="INVALID_ENV_ALLOWLIST"):
        load_config(save_config(existing_project, document))


def test_missing_project_env_has_actionable_redacted_error(existing_project, monkeypatch):
    monkeypatch.setenv("DSC_TEST_PASSWORD", "private-db-password")
    monkeypatch.delenv("PROJECT_REGION", raising=False)
    document = example_config(existing_project)
    document["env_allowlist"] = ["PROJECT_REGION"]
    result = CliRunner().invoke(
        main, ["doctor", "--config", str(save_config(existing_project, document))]
    )
    assert result.exit_code == 2
    assert "MISSING_PROJECT_ENV at $.env_allowlist[0]" in result.output
    assert "Export every variable" in result.output
    assert "private-db-password" not in result.output


def test_completed_cleanup_does_not_require_project_environment(existing_project, monkeypatch):
    monkeypatch.setenv("DSC_TEST_PASSWORD", "test-only-password")
    monkeypatch.delenv("PROJECT_REGION", raising=False)
    document = example_config(existing_project)
    document["env_allowlist"] = ["PROJECT_REGION"]
    path = save_config(existing_project, document)
    config = load_config(path, load_project_env=False)
    journal = Journal.create(config, uuid.uuid4().hex)
    journal.transition("CLEANED")
    result = CliRunner().invoke(
        main,
        [
            "cleanup",
            "--config",
            str(path),
            "--run-id",
            journal.data["run_id"],
        ],
    )
    assert result.exit_code == 0, result.output
    assert "CLEANED" in result.output


def test_diagnostics_point_to_a_bad_row_without_printing_values(tmp_path):
    original_project = ROOT / "examples/shop"
    scenario = copy.deepcopy(
        load_scenario(original_project / "scenarios/orders.yml", original_project).data
    )
    secret = "synthetic.private@example.invalid"
    scenario["steps"][0]["inputs"]["orders"]["replace"]["rows"][0]["amount"] = secret
    path = tmp_path / "bad.yml"
    path.write_text(yaml.safe_dump(scenario, sort_keys=False))
    with pytest.raises(ScenarioError) as error:
        load_scenario(path, tmp_path)
    rendered = display_error(error.value)
    assert "INVALID_TYPED_VALUE at $.steps[0].inputs[*].replace.rows[0][*]" in rendered
    assert "quote decimals" in rendered
    assert secret not in rendered


def test_schema_diagnostic_locates_a_missing_field(tmp_path):
    data = {"version": 1, "name": "missing_model"}
    path = tmp_path / "bad.yml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ScenarioError) as error:
        load_scenario(path, tmp_path)
    assert error.value.diagnostic()["location"] == "$.model"


def test_non_json_vars_have_a_located_error(tmp_path):
    original_project = ROOT / "examples/shop"
    scenario = copy.deepcopy(
        load_scenario(original_project / "scenarios/orders.yml", original_project).data
    )
    scenario["steps"][0]["run"]["vars"] = {"not_json": float("nan")}
    path = tmp_path / "bad.yml"
    path.write_text(yaml.safe_dump(scenario))
    with pytest.raises(ScenarioError) as error:
        load_scenario(path, tmp_path)
    assert error.value.code == "INVALID_RUN_VARS"
    assert error.value.diagnostic()["location"] == "$.steps[0].run.vars"


def test_duplicate_yaml_reports_line_without_its_value(tmp_path):
    path = tmp_path / "duplicate.yml"
    path.write_text("name: first\nname: synthetic.private@example.invalid\n")
    from dbt_scenario.loader import read_yaml

    with pytest.raises(ScenarioError) as error:
        read_yaml(path)
    rendered = display_error(error.value)
    assert "line 2, column 1" in rendered
    assert "synthetic.private" not in rendered


def test_missing_dependencies_are_found_without_database_access(existing_project, monkeypatch):
    monkeypatch.setenv("DSC_TEST_PASSWORD", "private-db-password")
    (existing_project / "packages.yml").write_text(
        "packages:\n  - package: dbt-labs/dbt_utils\n    version: '1.3.0'\n"
    )
    document = example_config(existing_project)
    result = CliRunner().invoke(
        main, ["doctor", "--config", str(save_config(existing_project, document))]
    )
    assert result.exit_code == 2
    assert "DEPENDENCIES_NOT_INSTALLED" in result.output
    assert "Run dbt deps" in result.output
    assert "private-db-password" not in result.output


def test_installed_hub_dependency_uses_project_metadata(existing_project):
    (existing_project / "packages.yml").write_text(
        "packages:\n  - package: dbt-labs/dbt_utils\n    version: '1.3.0'\n"
    )
    installed = existing_project / "dbt_packages/dbt_utils"
    installed.mkdir(parents=True)
    (installed / "dbt_project.yml").write_text("name: dbt_utils\nconfig-version: 2\n")
    check_dependencies(existing_project, project_settings(existing_project))


def test_dependency_location_cannot_point_outside_project(existing_project):
    (existing_project / "packages.yml").write_text(
        "packages:\n  - package: dbt-labs/dbt_utils\n    version: '1.3.0'\n"
    )
    settings = project_settings(existing_project)
    settings["packages-install-path"] = "../external-packages"
    with pytest.raises(ScenarioError, match="UNSUPPORTED_DEPENDENCY_LOCATION"):
        check_dependencies(existing_project, settings)
