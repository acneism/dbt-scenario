import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

SPEC = importlib.util.spec_from_file_location(
    "compare_approaches", Path(__file__).resolve().parents[1] / "scripts/compare_approaches.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("status,reason,code", [("PASS", None, 0), ("FAIL", "ROWS_MISMATCH", 1)])
def test_package_gate_accepts_only_matching_exit_and_assertion(status, reason, code):
    output = ("EVALUATION_GATE=" + json.dumps({"status": status, "reason_code": reason})).encode()
    result = CompletedProcess([], code, stdout=output, stderr=b"")
    assert MODULE.package_gate(result) == reason


@pytest.mark.parametrize(
    "status,reason,code",
    [
        ("PASS", None, 1),
        ("FAIL", "ROWS_MISMATCH", 0),
        ("PASS", "ROWS_MISMATCH", 0),
        ("FAIL", None, 1),
    ],
)
def test_execution_failures_and_inconsistent_results_are_not_assertion_failures(
    status, reason, code
):
    output = ("EVALUATION_GATE=" + json.dumps({"status": status, "reason_code": reason})).encode()
    with pytest.raises(RuntimeError, match="AUDIT_HELPER_GATE_INCONSISTENT"):
        MODULE.package_gate(CompletedProcess([], code, stdout=output, stderr=b""))


def test_missing_package_gate_cannot_be_treated_as_a_pass():
    with pytest.raises(RuntimeError, match="AUDIT_HELPER_GATE_MISSING"):
        MODULE.package_gate(CompletedProcess([], 0, stdout=b"no tests executed", stderr=b""))
