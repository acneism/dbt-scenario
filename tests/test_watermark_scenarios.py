import importlib
from pathlib import Path

import pytest

from dbt_scenario.loader import load_scenario, read_yaml


@pytest.mark.parametrize("case", ["newer_event", "same_timestamp", "older_event"])
@pytest.mark.parametrize("initial_only", [False, True])
def test_watermark_fixture_generation_roundtrips_through_strict_scenario_loader(
    tmp_path, monkeypatch, case, initial_only
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("check_watermarks")
    specification = read_yaml(module.ASSETS / "cases.yml")
    definition = module.build_scenario(case, specification, initial_only)
    path = tmp_path / "scenario.yml"
    module.write_yaml(path, definition)
    scenario = load_scenario(path, tmp_path)
    steps = scenario.data["steps"]
    assert len(steps) == (1 if initial_only else 3)
    expected = steps[0 if initial_only else 1]["expect"]["rows"]
    assert {row["user_id"] for row in expected} == {1, 2}
    assert all(row["courserun_readable_id"] == "Example/Demo/2026" for row in expected)
    if not initial_only:
        assert steps[-1]["expect"] == {"same_as": "arrival"}
