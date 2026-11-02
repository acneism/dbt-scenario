import copy
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from dbt_scenario.artifacts import successful_model_result
from dbt_scenario.errors import ScenarioError
from dbt_scenario.project import Project


@pytest.fixture
def invocation(tmp_path, monkeypatch):
    project = Project.__new__(Project)
    project.workspace = tmp_path
    project.root = tmp_path / "project"
    project.profiles = tmp_path / "profiles"
    project.environment = {}
    project.sequence = 0
    project.invocations = {}
    project.seen_invocations = set()
    change = {"mutate": lambda manifest, results: None, "exit": 0}

    def run(argv, environment, cwd, deadline):
        directory = tmp_path / f"dbt_{project.sequence}" / "target"
        directory.mkdir()
        now = datetime.now(UTC).isoformat()
        metadata = {
            "invocation_id": str(uuid.uuid4()),
            "generated_at": now,
            "invocation_started_at": now,
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
        }
        manifest = {"metadata": metadata, "nodes": {}, "macros": {}, "sources": {}}
        results = {
            "metadata": {
                **metadata,
                "dbt_schema_version": "https://schemas.getdbt.com/dbt/run-results/v6.json",
            },
            "args": {"which": "run", "full_refresh": False},
            "results": [{"unique_id": "model.shop.orders", "status": "success"}],
        }
        change["mutate"](manifest, results)
        for name, payload in [("manifest.json", manifest), ("run_results.json", results)]:
            if payload is not None:
                (directory / name).write_text(json.dumps(payload), encoding="utf-8")
        for name in change.get("missing", []):
            (directory / name).unlink()
        for name in change.get("malformed", []):
            (directory / name).write_text('{"secret":"synthetic-secret",')
        return change["exit"]

    monkeypatch.setattr("dbt_scenario.project.run_process", run)
    return project, change


def test_current_invocation_binds_manifest_and_results(invocation):
    project, _ = invocation
    manifest, directory = project.invoke("run", 10)
    results = project.read_run_results(directory)
    assert results["metadata"]["invocation_id"] == manifest["metadata"]["invocation_id"]
    successful_model_result(results, "model.shop.orders")


@pytest.mark.parametrize("name", ["manifest.json", "run_results.json"])
def test_required_artifact_cannot_be_missing(invocation, name):
    project, change = invocation
    change["missing"] = [name]
    with pytest.raises(ScenarioError, match="DBT_ARTIFACT_MISSING"):
        project.invoke("run", 10)


@pytest.mark.parametrize("name", ["manifest.json", "run_results.json"])
def test_broken_json_is_redacted(invocation, name):
    project, change = invocation
    change["malformed"] = [name]
    with pytest.raises(ScenarioError, match="DBT_ARTIFACT_INVALID") as error:
        project.invoke("run", 10)
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("kind", ["manifest", "results"])
@pytest.mark.parametrize("field", ["invocation_id", "generated_at", "invocation_started_at"])
def test_missing_metadata_cannot_verify_execution(invocation, kind, field):
    project, change = invocation

    def mutate(manifest, results):
        payload = manifest if kind == "manifest" else results
        payload["metadata"].pop(field)

    change["mutate"] = mutate
    with pytest.raises(ScenarioError, match="DBT_ARTIFACT_INVALID"):
        project.invoke("run", 10)


@pytest.mark.parametrize("offset", [-86400, 86400])
@pytest.mark.parametrize("kind", ["manifest", "results"])
def test_artifact_times_must_belong_to_current_process(invocation, offset, kind):
    project, change = invocation

    def mutate(manifest, results):
        payload = manifest if kind == "manifest" else results
        shifted = (datetime.now(UTC) + timedelta(seconds=offset)).isoformat()
        payload["metadata"].update(generated_at=shifted, invocation_started_at=shifted)

    change["mutate"] = mutate
    with pytest.raises(ScenarioError, match="DBT_ARTIFACT_STALE"):
        project.invoke("run", 10)


def test_results_from_another_invocation_cannot_pass(invocation):
    project, change = invocation
    change["mutate"] = lambda manifest, results: results["metadata"].update(
        invocation_id=str(uuid.uuid4())
    )
    with pytest.raises(ScenarioError, match="DBT_ARTIFACT_INVOCATION_MISMATCH"):
        project.invoke("run", 10)


def test_replayed_invocation_is_rejected_even_with_rewritten_times(invocation):
    project, change = invocation
    manifest, _ = project.invoke("parse", 10)
    original = manifest["metadata"]["invocation_id"]
    change["mutate"] = lambda manifest, results: manifest["metadata"].update(invocation_id=original)
    with pytest.raises(ScenarioError, match="DBT_ARTIFACT_STALE"):
        project.invoke("parse", 10)


def test_artifacts_are_rechecked_before_assertions(invocation):
    project, _ = invocation
    _, directory = project.invoke("run", 10)
    path = directory / "target/run_results.json"
    results = json.loads(path.read_text())
    results["metadata"]["invocation_id"] = str(uuid.uuid4())
    path.write_text(json.dumps(results))
    with pytest.raises(ScenarioError, match="DBT_ARTIFACT_INVOCATION_MISMATCH"):
        project.read_run_results(directory)


@pytest.mark.parametrize("full_refresh", [True, 0, "false"])
def test_unknown_or_forced_refresh_cannot_verify_incremental_run(invocation, full_refresh):
    project, change = invocation
    change["mutate"] = lambda manifest, results: results["args"].update(full_refresh=full_refresh)
    with pytest.raises(ScenarioError, match="EXECUTION_MODE_UNVERIFIED"):
        project.invoke("run", 10)


def test_dbt_default_null_refresh_flag_is_supported(invocation):
    project, change = invocation
    change["mutate"] = lambda manifest, results: results["args"].update(full_refresh=None)
    project.invoke("run", 10)


def test_dbt_omitted_default_refresh_flag_is_supported(invocation):
    project, change = invocation
    change["mutate"] = lambda manifest, results: results["args"].pop("full_refresh")
    project.invoke("run", 10)


def test_existing_artifact_directory_is_not_reused(invocation):
    project, _ = invocation
    (project.workspace / "dbt_1").mkdir()
    with pytest.raises(ScenarioError, match="DBT_ARTIFACT_DIRECTORY_EXISTS"):
        project.invoke("run", 10)


def test_nonzero_dbt_exit_overrides_successful_artifacts(invocation):
    project, change = invocation
    change["exit"] = 1
    with pytest.raises(ScenarioError, match="DBT_EXECUTION_ERROR"):
        project.invoke("run", 10)


@pytest.mark.parametrize(
    "results",
    [
        [],
        [{"unique_id": "model.shop.orders", "status": "skipped"}],
        [{"unique_id": "model.shop.orders", "status": "error"}],
        [{"unique_id": "model.shop.other", "status": "success"}],
        [{"unique_id": "model.shop.orders"}],
        [{"unique_id": "model.shop.orders", "status": "success"}] * 2,
        [
            {"unique_id": "model.shop.orders", "status": "success"},
            {"unique_id": "model.shop.other", "status": "success"},
        ],
    ],
)
def test_exactly_one_successful_selected_model_is_required(results):
    with pytest.raises(ScenarioError, match="DBT_MODEL_NOT_SUCCESSFUL"):
        successful_model_result({"results": copy.deepcopy(results)}, "model.shop.orders")
