import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "resource_limits", Path(__file__).resolve().parents[1] / "scripts/resource_limits.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    "cpu,memory,swap,verified",
    [
        ("200000 100000", "8589934592", "0", True),
        ("max 100000", "8589934592", "0", False),
        ("400000 100000", "8589934592", "0", False),
        ("200000 100000", "max", "0", False),
        ("200000 100000", "8589934592", "8589934592", False),
        ("invalid", "8589934592", "0", False),
    ],
)
def test_only_verified_target_limits_can_support_a_performance_claim(
    tmp_path, cpu, memory, swap, verified
):
    for name, value in [("cpu.max", cpu), ("memory.max", memory), ("memory.swap.max", swap)]:
        (tmp_path / name).write_text(value)
    assert MODULE.resource_limits(tmp_path)["verified"] is verified


def test_absent_cgroups_do_not_claim_enforcement(tmp_path):
    assert MODULE.resource_limits(tmp_path)["verified"] is False
