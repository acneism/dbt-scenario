import copy
import json
import re
from importlib.resources import files
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator

from dbt_scenario.errors import ScenarioError
from dbt_scenario.loader import sql_type
from dbt_scenario.requirements import check_model_config


def unique_pairs(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ScenarioError("INIT_METADATA_INVALID")
    return result


def reject_json_constant(value):
    raise ScenarioError("INIT_METADATA_INVALID")


def read_metadata(path: Path, schema: str):
    try:
        with path.open("rb") as source:
            content = source.read(64 * 1024 * 1024 + 1)
        if len(content) > 64 * 1024 * 1024:
            raise ScenarioError("FILE_TOO_LARGE")
        document = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=reject_json_constant,
        )
        if (
            not isinstance(document, dict)
            or not isinstance(document.get("metadata"), dict)
            or document["metadata"].get("dbt_schema_version") != schema
            or any(not isinstance(document.get(key), dict) for key in ["nodes", "sources"])
        ):
            raise ScenarioError("INIT_METADATA_INVALID")
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise ScenarioError("INIT_METADATA_INVALID") from None
    return document


def column_types(node, location, catalog=False):
    columns = node.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise ScenarioError("INIT_COLUMNS_MISSING", location=location)
    entries = list(columns.items())
    if catalog:
        indexes = [info.get("index") if isinstance(info, dict) else None for _, info in entries]
        if any(type(index) is not int or index < 1 for index in indexes) or len(
            set(indexes)
        ) != len(indexes):
            raise ScenarioError("INIT_METADATA_INVALID")
        entries.sort(key=lambda item: item[1]["index"])
    result = {}
    for name, info in entries:
        if (
            not isinstance(name, str)
            or not name
            or "\x00" in name
            or not isinstance(info, dict)
            or info.get("name") != name
        ):
            raise ScenarioError("INIT_METADATA_INVALID", location=location)
        try:
            if len(name.encode("utf-8")) > 63:
                raise ValueError
        except (ValueError, UnicodeError):
            raise ScenarioError("INIT_METADATA_INVALID", location=location) from None
        kind = info.get("type" if catalog else "data_type")
        if not isinstance(kind, str) or not kind.strip():
            raise ScenarioError("INIT_COLUMN_TYPE_MISSING", location=(*location, name))
        normalized = re.sub(r"\s+", "", kind.lower())
        aliases = {
            "int": "integer",
            "int4": "integer",
            "int8": "bigint",
            "bool": "boolean",
            "timestampwithouttimezone": "timestamp",
            "timestampwithtimezone": "timestamptz",
        }
        normalized = aliases.get(normalized, normalized)
        normalized = re.sub(r"^decimal\(", "numeric(", normalized)
        try:
            result[name] = sql_type(normalized)
        except ScenarioError as error:
            raise ScenarioError(error.code, location=(*location, name)) from None
    return result


def scaffold(settings, selector, manifest_path, catalog_path=None, primary_key=()):
    manifest = read_metadata(manifest_path, "https://schemas.getdbt.com/dbt/manifest/v12.json")
    project = settings["name"]
    metadata = manifest["metadata"]
    if metadata.get("adapter_type") != "postgres":
        raise ScenarioError("INIT_ADAPTER_UNSUPPORTED")
    if metadata.get("project_name") is not None and metadata["project_name"] != project:
        raise ScenarioError("INIT_PROJECT_MISMATCH")
    candidates = [
        (identity, node)
        for identity, node in manifest["nodes"].items()
        if isinstance(node, dict)
        and node.get("resource_type") == "model"
        and node.get("package_name") == project
        and (selector == identity or selector == node.get("name"))
    ]
    if not candidates:
        raise ScenarioError("MODEL_NOT_FOUND")
    if len(candidates) != 1:
        raise ScenarioError("INIT_MODEL_AMBIGUOUS")
    identity, model = candidates[0]
    name = model.get("name")
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9_]{1,120}", name)
        or identity != f"model.{project}.{name}"
        or model.get("unique_id") != identity
        or model.get("version") is not None
    ):
        raise ScenarioError("DIRECT_BUILTIN_OR_VERSIONED_REF_UNSUPPORTED")
    check_model_config(model.get("config"))
    depends_on = model.get("depends_on")
    dependencies = depends_on.get("nodes") if isinstance(depends_on, dict) else None
    if (
        not isinstance(dependencies, list)
        or not dependencies
        or any(not isinstance(item, str) for item in dependencies)
        or len(set(dependencies)) != len(dependencies)
    ):
        raise ScenarioError("INPUT_DEPENDENCIES_MISMATCH")
    catalog = None
    if catalog_path:
        catalog = read_metadata(catalog_path, "https://schemas.getdbt.com/dbt/catalog/v1.json")
        try:
            invocation = str(UUID(metadata["invocation_id"]))
            if invocation != str(UUID(catalog["metadata"]["invocation_id"])):
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ScenarioError("INIT_CATALOG_MISMATCH") from None
        if catalog.get("errors"):
            raise ScenarioError("INIT_CATALOG_MISMATCH")

    def columns(node_id, node, location):
        if catalog is None:
            return column_types(node, location)
        collection = "sources" if node_id.startswith("source.") else "nodes"
        entry = catalog[collection].get(node_id)
        if not isinstance(entry, dict) or (
            entry.get("unique_id") is not None and entry["unique_id"] != node_id
        ):
            raise ScenarioError("INIT_CATALOG_MISMATCH", location=location)
        return column_types(entry, location, catalog=True)

    inputs = {}
    for index, dependency in enumerate(dependencies):
        kind = dependency.split(".")[0]
        collection = "sources" if kind == "source" else "nodes"
        node = manifest[collection].get(dependency)
        if (
            kind not in {"source", "model"}
            or not dependency.startswith(f"{kind}.{project}.")
            or not isinstance(node, dict)
            or node.get("unique_id") != dependency
            or node.get("resource_type") != kind
            or node.get("package_name") != project
        ):
            raise ScenarioError("INPUT_DEPENDENCY_UNSUPPORTED")
        if kind == "model":
            config = node.get("config")
            if not isinstance(config, dict):
                raise ScenarioError("INIT_METADATA_INVALID")
            if config.get("materialized") == "ephemeral":
                raise ScenarioError("EPHEMERAL_INPUT_UNSUPPORTED")
            if node.get("version") is not None:
                raise ScenarioError("DIRECT_BUILTIN_OR_VERSIONED_REF_UNSUPPORTED")
        inputs[f"input_{index + 1}"] = {
            "node": dependency,
            "columns": columns(dependency, node, ("inputs", index, "columns")),
        }
    output = columns(identity, model, ("output", "columns"))
    keys = list(primary_key) if primary_key else model["config"].get("unique_key")
    if isinstance(keys, str):
        keys = [keys]
    if (
        not isinstance(keys, list)
        or not keys
        or any(not isinstance(key, str) or key not in output for key in keys)
        or len(set(keys)) != len(keys)
    ):
        raise ScenarioError("INIT_PRIMARY_KEY_REQUIRED")
    scenario = {
        "version": 1,
        "name": "test_" + name[:75],
        "model": identity,
        "inputs": inputs,
        "output": {"columns": output, "primary_key": keys},
        "steps": [
            {
                "name": mode,
                "inputs": {
                    key: {"replace": {"rows": f"replace_with_{mode}_{key}_rows"}} for key in inputs
                },
                "run": {"mode": mode},
                "expect": {"rows": f"replace_with_expected_{mode}_rows"},
            }
            for mode in ["initial", "incremental"]
        ]
        + [
            {
                "name": "retry",
                "run": {"mode": "incremental"},
                "expect": {"same_as": "incremental"},
            }
        ],
    }
    prototype = copy.deepcopy(scenario)
    for step in prototype["steps"]:
        for update in step.get("inputs", {}).values():
            update["replace"]["rows"] = []
        if "rows" in step["expect"]:
            step["expect"]["rows"] = []
    schema = json.loads(files("dbt_scenario").joinpath("scenario.schema.json").read_text())
    if next(Draft202012Validator(schema).iter_errors(prototype), None):
        raise ScenarioError("INIT_TEMPLATE_UNSUPPORTED")
    return name, scenario
