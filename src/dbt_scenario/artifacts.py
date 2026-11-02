import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from dbt_scenario.errors import ScenarioError


def read_artifact(artifact_dir: Path, name: str) -> dict:
    try:
        payload = json.loads((artifact_dir / "target" / name).read_text(encoding="utf-8"))
    except OSError:
        raise ScenarioError("DBT_ARTIFACT_MISSING") from None
    except (ValueError, UnicodeError):
        raise ScenarioError("DBT_ARTIFACT_INVALID") from None
    if not isinstance(payload, dict):
        raise ScenarioError("DBT_ARTIFACT_INVALID")
    return payload


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError
    return parsed


def validate_metadata(payload, kind, started, finished, expected_id=None):
    schemas = {"manifest": 12, "run-results": 6}
    try:
        metadata = payload["metadata"]
        invocation_id = str(UUID(metadata["invocation_id"]))
        generated = timestamp(metadata["generated_at"])
        invoked = timestamp(metadata["invocation_started_at"])
        if (
            metadata["dbt_schema_version"]
            != f"https://schemas.getdbt.com/dbt/{kind}/v{schemas[kind]}.json"
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ScenarioError("DBT_ARTIFACT_INVALID") from None
    if not started <= invoked <= generated <= finished:
        raise ScenarioError("DBT_ARTIFACT_STALE")
    if expected_id is not None and invocation_id != expected_id:
        raise ScenarioError("DBT_ARTIFACT_INVOCATION_MISMATCH")
    return invocation_id


def successful_model_result(payload, model_id):
    results = payload.get("results")
    if not isinstance(results, list) or any(not isinstance(entry, dict) for entry in results):
        raise ScenarioError("DBT_ARTIFACT_INVALID")
    if (
        len(results) != 1
        or results[0].get("unique_id") != model_id
        or results[0].get("status") != "success"
    ):
        raise ScenarioError("DBT_MODEL_NOT_SUCCESSFUL")
