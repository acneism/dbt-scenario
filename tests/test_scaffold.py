import copy
import json
import uuid

import pytest
from click.testing import CliRunner

from dbt_scenario.cli import main
from dbt_scenario.errors import ScenarioError
from dbt_scenario.initialize import initialize
from dbt_scenario.loader import load_scenario, read_yaml


@pytest.fixture
def artifacts(tmp_path):
    (tmp_path / "dbt_project.yml").write_text("name: analytics\nconfig-version: 2\n")
    columns = {
        "order_id": {"name": "order_id", "data_type": "INT8"},
        "amount": {"name": "amount", "data_type": "numeric (12, 2)"},
    }
    source_id, parent_id, model_id = (
        "source.analytics.raw.orders",
        "model.analytics.stg_orders",
        "model.analytics.fct_orders",
    )
    metadata = {
        "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
        "adapter_type": "postgres",
        "project_name": "analytics",
        "invocation_id": str(uuid.uuid4()),
    }
    manifest = {
        "metadata": metadata,
        "nodes": {
            model_id: {
                "unique_id": model_id,
                "name": "fct_orders",
                "package_name": "analytics",
                "resource_type": "model",
                "config": {"materialized": "incremental", "unique_key": "order_id"},
                "columns": copy.deepcopy(columns),
                "depends_on": {"nodes": [parent_id, source_id]},
                "raw_code": "synthetic.private@example.invalid",
            },
            parent_id: {
                "unique_id": parent_id,
                "name": "stg_orders",
                "package_name": "analytics",
                "resource_type": "model",
                "config": {"materialized": "view"},
                "columns": copy.deepcopy(columns),
            },
        },
        "sources": {
            source_id: {
                "unique_id": source_id,
                "name": "orders",
                "package_name": "analytics",
                "resource_type": "source",
                "columns": copy.deepcopy(columns),
            }
        },
    }
    catalog = {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/catalog/v1.json",
            "invocation_id": metadata["invocation_id"],
        },
        "nodes": {},
        "sources": {},
    }
    for collection in ["nodes", "sources"]:
        for identity in manifest[collection]:
            catalog[collection][identity] = {
                "unique_id": identity,
                "columns": {
                    "amount": {"name": "amount", "index": 2, "type": "numeric(12,2)"},
                    "order_id": {"name": "order_id", "index": 1, "type": "bigint"},
                },
                "stats": {"private": {"value": "synthetic.private@example.invalid"}},
            }
    return tmp_path, manifest, catalog


def generate(artifacts, *, with_catalog=False, **kwargs):
    root, manifest, catalog = artifacts
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    catalog_path = root / "catalog.json"
    catalog_path.write_text(json.dumps(catalog))
    return initialize(
        root,
        model=kwargs.pop("model", "fct_orders"),
        manifest_path=manifest_path,
        catalog_path=catalog_path if with_catalog else None,
        **kwargs,
    )


@pytest.mark.parametrize("with_catalog", [False, True])
def test_metadata_template_uses_real_ids_and_types_but_requires_explicit_rows(
    artifacts, with_catalog, monkeypatch
):
    root, _, _ = artifacts
    monkeypatch.delenv("DSC_TEST_PASSWORD", raising=False)
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: pytest.fail("database accessed"))
    created = generate(artifacts, with_catalog=with_catalog)
    assert created == ["scenario-runner.yml", "scenarios/fct_orders.yml"]
    path = root / "scenarios/fct_orders.yml"
    text = path.read_text()
    assert "synthetic.private@example.invalid" not in text
    data = read_yaml(path)
    assert data["model"] == "model.analytics.fct_orders"
    assert [entry["node"] for entry in data["inputs"].values()] == [
        "model.analytics.stg_orders",
        "source.analytics.raw.orders",
    ]
    assert data["output"] == {
        "columns": {"order_id": "bigint", "amount": "numeric(12,2)"},
        "primary_key": ["order_id"],
    }
    assert data["steps"][2]["expect"] == {"same_as": "incremental"}
    with pytest.raises(ScenarioError, match="UNFILLED_TEMPLATE_ROWS"):
        load_scenario(path, root)


def test_catalog_supplies_schema_when_manifest_has_no_declared_columns(artifacts):
    root, manifest, _ = artifacts
    for collection in ["nodes", "sources"]:
        for node in manifest[collection].values():
            node["columns"] = {}
    generate(artifacts, with_catalog=True)
    data = read_yaml(root / "scenarios/fct_orders.yml")
    assert list(data["output"]["columns"]) == ["order_id", "amount"]


def test_additional_template_preserves_existing_configuration_and_refuses_overwrite(artifacts):
    root, _, _ = artifacts
    config = root / "scenario-runner.yml"
    config.write_text("user configuration must survive\n")
    created = generate(artifacts)
    assert created == ["scenarios/fct_orders.yml"]
    assert config.read_text() == "user configuration must survive\n"
    scenario = root / "scenarios/fct_orders.yml"
    scenario.write_text("user scenario must survive\n")
    with pytest.raises(ScenarioError, match="INIT_WOULD_OVERWRITE"):
        generate(artifacts)
    assert scenario.read_text() == "user scenario must survive\n"
    assert config.read_text() == "user configuration must survive\n"


def test_second_scenario_for_same_model_gets_a_distinct_safe_name(artifacts):
    root, _, _ = artifacts
    generate(artifacts)
    config = (root / "scenario-runner.yml").read_bytes()
    first = (root / "scenarios/fct_orders.yml").read_bytes()
    created = generate(artifacts, scenario_name="orders_late_arrival")
    assert created == ["scenarios/orders_late_arrival.yml"]
    data = read_yaml(root / "scenarios/orders_late_arrival.yml")
    assert data["name"] == "orders_late_arrival"
    assert (root / "scenario-runner.yml").read_bytes() == config
    assert (root / "scenarios/fct_orders.yml").read_bytes() == first


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "CON", "NUL", "x" * 81, ""])
def test_scenario_names_cannot_escape_or_use_device_files(artifacts, name):
    root, _, _ = artifacts
    with pytest.raises(ScenarioError, match="INIT_SCENARIO_NAME_INVALID"):
        generate(artifacts, scenario_name=name)
    assert not (root / "scenario-runner.yml").exists()


@pytest.mark.parametrize("value", [None, "", "md5(order_id)", ["order_id", "order_id"]])
def test_missing_or_expression_key_requires_explicit_valid_output_columns(artifacts, value):
    root, manifest, _ = artifacts
    manifest["nodes"]["model.analytics.fct_orders"]["config"]["unique_key"] = value
    with pytest.raises(ScenarioError, match="INIT_PRIMARY_KEY_REQUIRED"):
        generate(artifacts)
    assert not (root / "scenario-runner.yml").exists()
    generate(artifacts, primary_key=("order_id", "amount"))
    assert read_yaml(root / "scenarios/fct_orders.yml")["output"]["primary_key"] == [
        "order_id",
        "amount",
    ]


@pytest.mark.parametrize(
    "kind",
    [
        "jsonb",
        "double precision",
        "varchar(80)",
        "numeric",
        "smallint",
        "in teger",
        "big int",
        "time stamp",
        "timestampwithouttimezone",
        "nu meric(12,2)",
    ],
)
def test_incompatible_types_are_not_guessed_or_upcast(artifacts, kind):
    root, manifest, _ = artifacts
    manifest["nodes"]["model.analytics.fct_orders"]["columns"]["amount"]["data_type"] = kind
    with pytest.raises(ScenarioError, match="UNSUPPORTED_COLUMN_TYPE"):
        generate(artifacts)
    assert not (root / "scenario-runner.yml").exists()
    assert not (root / "scenarios").exists()


@pytest.mark.parametrize(
    "change,code",
    [
        ("adapter", "INIT_ADAPTER_UNSUPPORTED"),
        ("project", "INIT_PROJECT_MISMATCH"),
        ("columns", "INIT_COLUMNS_MISSING"),
        ("type", "INIT_COLUMN_TYPE_MISSING"),
        ("dependencies", "INPUT_DEPENDENCIES_MISMATCH"),
        ("ephemeral", "EPHEMERAL_INPUT_UNSUPPORTED"),
        ("seed", "INPUT_DEPENDENCY_UNSUPPORTED"),
        ("hooks", "MODEL_HOOKS_UNSUPPORTED"),
        ("contract", "MODEL_CONFIG_UNSUPPORTED"),
        ("strategy", "UNSUPPORTED_INCREMENTAL_STRATEGY"),
        ("refresh", "UNSUPPORTED_MATERIALIZATION"),
    ],
)
def test_unsupported_metadata_fails_before_any_template_write(artifacts, change, code):
    root, manifest, _ = artifacts
    model = manifest["nodes"]["model.analytics.fct_orders"]
    if change == "adapter":
        manifest["metadata"]["adapter_type"] = "snowflake"
    elif change == "project":
        manifest["metadata"]["project_name"] = "other"
    elif change == "columns":
        model["columns"] = {}
    elif change == "type":
        model["columns"]["amount"]["data_type"] = None
    elif change == "dependencies":
        model["depends_on"] = []
    elif change == "ephemeral":
        manifest["nodes"]["model.analytics.stg_orders"]["config"]["materialized"] = "ephemeral"
    elif change == "seed":
        model["depends_on"]["nodes"] = ["seed.analytics.seed_orders"]
    elif change == "hooks":
        model["config"]["post-hook"] = ["select 1"]
    elif change == "contract":
        model["config"]["contract"] = {"enforced": True}
    elif change == "strategy":
        model["config"]["incremental_strategy"] = []
    elif change == "refresh":
        model["config"]["full_refresh"] = True
    with pytest.raises(ScenarioError, match=code):
        generate(artifacts)
    assert not (root / "scenario-runner.yml").exists()


@pytest.mark.parametrize("change", ["invocation", "missing_model", "errors", "column_indexes"])
def test_catalog_must_be_complete_and_paired_with_manifest(artifacts, change):
    root, _, catalog = artifacts
    if change == "invocation":
        catalog["metadata"]["invocation_id"] = str(uuid.uuid4())
    elif change == "missing_model":
        catalog["nodes"].pop("model.analytics.fct_orders")
    elif change == "errors":
        catalog["errors"] = ["synthetic.private@example.invalid"]
    else:
        catalog["nodes"]["model.analytics.fct_orders"]["columns"]["amount"]["index"] = 1
    with pytest.raises(ScenarioError, match="INIT_CATALOG_MISMATCH|INIT_METADATA_INVALID"):
        generate(artifacts, with_catalog=True)
    assert not (root / "scenario-runner.yml").exists()


def test_cli_rejects_invalid_flag_combinations_without_writing(artifacts):
    root, _, _ = artifacts
    result = CliRunner().invoke(main, ["init", "--project-dir", str(root), "--model", "fct_orders"])
    assert result.exit_code == 2
    assert "INIT_OPTIONS_INVALID" in result.output
    assert not (root / "scenario-runner.yml").exists()


def test_cli_reports_missing_metadata_without_exposing_values(artifacts):
    root, manifest, _ = artifacts
    model = manifest["nodes"]["model.analytics.fct_orders"]
    model["columns"]["amount"]["data_type"] = "synthetic.private@example.invalid"
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = CliRunner().invoke(
        main,
        ["init", "--project-dir", str(root), "--model", "fct_orders", "--manifest", str(path)],
    )
    assert result.exit_code == 2
    assert "UNSUPPORTED_COLUMN_TYPE" in result.output
    assert "synthetic.private@example.invalid" not in result.output


@pytest.mark.parametrize("content", ['{"nodes":{},"nodes":{}}', "[]", '{"metadata":'])
def test_malformed_or_duplicate_json_is_rejected(artifacts, content):
    root, _, _ = artifacts
    path = root / "invalid.json"
    path.write_text(content)
    with pytest.raises(ScenarioError, match="INIT_METADATA_INVALID"):
        initialize(root, model="fct_orders", manifest_path=path)
    assert not (root / "scenario-runner.yml").exists()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_json_constants_in_otherwise_valid_metadata_are_rejected(artifacts, value):
    root, manifest, _ = artifacts
    manifest["unused_statistic"] = value
    with pytest.raises(ScenarioError, match="INIT_METADATA_INVALID"):
        generate(artifacts)
    assert not (root / "scenario-runner.yml").exists()
