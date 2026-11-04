import copy
import importlib
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def external_gate(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("check_external_postgres")


def counterexample_report():
    steps = []
    for index, status in enumerate(["PASS", "FAIL"]):
        steps.append(
            {
                "status": status,
                "actual_rows": 2,
                "reason_code": "ROWS_MISMATCH" if index else None,
                "diff_counts": {"missing": 1 if index else 0, "unexpected": 0, "changed": 0},
                "sql_audit": {"status": "PASS"},
                "observed_mode_evidence": {
                    "operation": "delete+insert" if index else "create_table",
                    "statement_sha256": "a" * 64,
                    "invocation_id": str(uuid.uuid4()),
                },
            }
        )
    steps.append({"status": "NOT_RUN", "reason_code": "PREVIOUS_STEP_UNSUCCESSFUL"})
    return {
        "overall_status": "FAIL",
        "reason_code": None,
        "cleanup_status": "CLEANED",
        "steps": steps,
    }


def test_external_counterexample_reads_the_assertion_reason_from_its_failed_step(external_gate):
    report = counterexample_report()
    external_gate.validate_report(report, "late_sensor")
    assert report["reason_code"] is None


@pytest.mark.parametrize(
    "fault", ["execution_error", "wrong_reason", "wrong_difference", "no_audit"]
)
def test_external_counterexample_cannot_count_errors_or_wrong_results_as_detection(
    external_gate, fault
):
    report = copy.deepcopy(counterexample_report())
    if fault == "execution_error":
        report.update(overall_status="ERROR", reason_code="DATABASE_ERROR")
    elif fault == "wrong_reason":
        report["steps"][1]["reason_code"] = "SCHEMA_MISMATCH"
    elif fault == "wrong_difference":
        report["steps"][1]["diff_counts"] = {"missing": 0, "unexpected": 0, "changed": 1}
    else:
        report["steps"][1]["sql_audit"]["status"] = "ERROR"
    with pytest.raises(RuntimeError):
        external_gate.validate_report(report, "late_sensor")
