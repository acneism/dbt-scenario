import copy
import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from dbt_scenario.cli import main
from dbt_scenario.loader import read_yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def definition(tmp_path):
    project = tmp_path / "shop"
    shutil.copytree(ROOT / "examples/shop", project, ignore=shutil.ignore_patterns(".dbt-scenario"))
    scenario = project / "scenarios/orders.yml"
    return project, scenario, read_yaml(scenario)


def invoke(project, path):
    return CliRunner().invoke(
        main, ["validate", "--project-dir", str(project), "--scenario", str(path)]
    )


def test_static_validation_needs_no_password_database_or_dbt_process(definition, monkeypatch):
    project, path, _ = definition
    monkeypatch.delenv("DSC_TEST_PASSWORD", raising=False)
    monkeypatch.delenv("DBT_ENV_SECRET_DSC_PASSWORD", raising=False)
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: pytest.fail("database accessed"))
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: pytest.fail("subprocess started"))
    result = invoke(project, path)
    assert result.exit_code == 0, result.output
    assert "VALID definition:" in result.output
    assert "plan and test" in result.output
    assert not (project / ".dbt-scenario").exists()


@pytest.mark.parametrize("step", [0, 1])
@pytest.mark.parametrize("kind", ["input", "expected"])
def test_inline_template_rows_get_a_specific_redacted_diagnostic(definition, step, kind):
    project, path, data = definition
    placeholder = "replace_with_private_canary_9_rows"
    if kind == "input":
        data["steps"][step]["inputs"]["orders"]["replace"] = {"rows": placeholder}
    else:
        data["steps"][step]["expect"] = {"rows": placeholder}
    path.write_text(yaml.safe_dump(data))
    result = invoke(project, path)
    assert result.exit_code == 2
    assert "UNFILLED_TEMPLATE_ROWS" in result.output
    assert f"$.steps[{step}]" in result.output
    assert "explicit YAML row list" in result.output
    assert placeholder not in result.output
    assert "private_canary_9" not in result.output


def test_external_fixture_placeholder_gets_the_same_actionable_error(definition):
    project, path, _ = definition
    fixture = project / "scenarios/fixtures/initial.yml"
    fixture.write_text("rows: replace_with_expected_initial_rows\n")
    result = invoke(project, path)
    assert result.exit_code == 2
    assert "UNFILLED_TEMPLATE_ROWS" in result.output


def test_placeholder_spelling_inside_a_real_text_cell_remains_valid(definition):
    project, path, data = definition
    data["inputs"]["orders"]["columns"]["note"] = "text"
    data["output"]["columns"]["note"] = "text"
    for name in ["initial", "updated"]:
        fixture = project / f"scenarios/fixtures/{name}.yml"
        rows = read_yaml(fixture)["rows"]
        for row in rows:
            row["note"] = "replace_with_expected_initial_rows"
        fixture.write_text(yaml.safe_dump({"rows": rows}))
    path.write_text(yaml.safe_dump(data))
    assert invoke(project, path).exit_code == 0


def test_other_invalid_strings_keep_the_schema_error(definition):
    project, path, data = definition
    data["steps"][0]["expect"] = {"rows": "not a row list"}
    path.write_text(yaml.safe_dump(data))
    result = invoke(project, path)
    assert result.exit_code == 2
    assert "INVALID_SCENARIO_SCHEMA" in result.output
    assert "UNFILLED_TEMPLATE_ROWS" not in result.output


def test_value_errors_are_found_without_revealing_fixture_values(definition):
    project, path, _ = definition
    fixture = project / "scenarios/fixtures/initial.yml"
    rows = read_yaml(fixture)["rows"]
    rows[0]["amount"] = "synthetic.private@example.invalid"
    fixture.write_text(yaml.safe_dump({"rows": rows}))
    result = invoke(project, path)
    assert result.exit_code == 2
    assert "INVALID_TYPED_VALUE" in result.output
    assert "synthetic.private@example.invalid" not in result.output


def test_duplicate_expected_keys_are_refused_before_execution(definition):
    project, path, _ = definition
    fixture = project / "scenarios/fixtures/initial.yml"
    rows = read_yaml(fixture)["rows"]
    rows.append(copy.deepcopy(rows[0]))
    fixture.write_text(yaml.safe_dump({"rows": rows}))
    result = invoke(project, path)
    assert result.exit_code == 2
    assert "INVALID_EXPECTED_KEY" in result.output


def test_definition_validation_does_not_claim_model_existence_or_sql_correctness(definition):
    project, path, data = definition
    data["model"] = "model.shop.not_created_yet"
    path.write_text(yaml.safe_dump(data))
    result = invoke(project, path)
    assert result.exit_code == 0
    assert "VALID definition:" in result.output
    assert "Next: plan and test" in result.output


def test_static_validation_preserves_project_path_boundary(definition, tmp_path):
    project, path, _ = definition
    outside = tmp_path / "outside.yml"
    outside.write_bytes(path.read_bytes())
    result = invoke(project, outside)
    assert result.exit_code == 2
    assert "SCENARIO_OUTSIDE_PROJECT" in result.output
