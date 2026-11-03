from dbt_scenario.errors import ScenarioError
from dbt_scenario.requirements import project_settings
from dbt_scenario.scaffold import (
    load_scaffold_metadata,
    scaffold_from_metadata,
    scenario_filename,
)


def discover_models(project_dir, manifest_path, catalog_path=None):
    settings = project_settings(project_dir)
    manifest, catalog = load_scaffold_metadata(settings, manifest_path, catalog_path)
    models = []
    actionable = {
        "INIT_PRIMARY_KEY_REQUIRED": "NEEDS_PRIMARY_KEY",
        "INIT_COLUMNS_MISSING": "NEEDS_COLUMN_TYPES",
        "INIT_COLUMN_TYPE_MISSING": "NEEDS_COLUMN_TYPES",
        "INIT_SCENARIO_NAME_INVALID": "NEEDS_SCENARIO_NAME",
    }
    counts = dict.fromkeys(
        [
            "TEMPLATE_READY",
            "NEEDS_PRIMARY_KEY",
            "NEEDS_COLUMN_TYPES",
            "NEEDS_SCENARIO_NAME",
            "BLOCKED",
        ],
        0,
    )
    for identity, node in sorted(manifest["nodes"].items()):
        if (
            not isinstance(node, dict)
            or node.get("resource_type") != "model"
            or node.get("package_name") != settings["name"]
            or not isinstance(node.get("config"), dict)
            or node["config"].get("materialized") != "incremental"
        ):
            continue
        entry = {"model": identity, "status": "TEMPLATE_READY", "reason_code": None}
        try:
            name, scenario = scaffold_from_metadata(settings, identity, manifest, catalog)
            scenario_filename(name)
            entry["input_count"] = len(scenario["inputs"])
        except ScenarioError as error:
            entry.update(
                status=actionable.get(error.code, "BLOCKED"),
                reason_code=error.code,
                diagnostic=error.diagnostic(),
            )
        counts[entry["status"]] += 1
        models.append(entry)
    return {
        "schema_version": 1,
        "project": settings["name"],
        "scope": "template_initialization",
        "execution_checked": False,
        "catalog_used": catalog is not None,
        "summary": counts,
        "models": models,
    }
