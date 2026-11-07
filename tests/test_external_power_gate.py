import importlib
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def power_gate(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("check_external_power")


def empty_start_report():
    return {
        "overall_status": "FAIL",
        "reason_code": None,
        "cleanup_status": "CLEANED",
        "steps": [
            {
                "status": "FAIL" if index else "PASS",
                "actual_rows": 0,
                "reason_code": "ROWS_MISMATCH" if index else None,
                "diff_counts": {"missing": index, "unexpected": 0, "changed": 0},
                "sql_audit": {"status": "PASS"},
                "observed_mode_evidence": {
                    "operation": "merge" if index else "create_table",
                    "statement_sha256": "a" * 64,
                    "invocation_id": str(uuid.uuid4()),
                },
            }
            for index in [0, 1]
        ]
        + [{"status": "NOT_RUN", "reason_code": "PREVIOUS_STEP_UNSUCCESSFUL"}],
    }


def test_external_power_empty_start_accepts_only_the_expected_missing_row(power_gate):
    power_gate.validate_report(empty_start_report(), "empty_start")


@pytest.mark.parametrize(
    "fault",
    [
        "execution_error",
        "wrong_assertion",
        "changed_row",
        "no_audit",
        "full_refresh",
        "cleanup",
        "invalid_digest",
    ],
)
def test_external_power_does_not_count_other_failures_as_detection(power_gate, fault):
    report = empty_start_report()
    if fault == "execution_error":
        report.update(overall_status="ERROR", reason_code="DATABASE_ERROR")
    elif fault == "wrong_assertion":
        report["steps"][1]["reason_code"] = "SCHEMA_MISMATCH"
    elif fault == "changed_row":
        report["steps"][1]["diff_counts"] = {"missing": 0, "unexpected": 0, "changed": 1}
    elif fault == "no_audit":
        report["steps"][1]["sql_audit"]["status"] = "ERROR"
    elif fault == "full_refresh":
        report["steps"][1]["observed_mode_evidence"]["operation"] = "create_table"
    elif fault == "invalid_digest":
        report["steps"][1]["observed_mode_evidence"]["statement_sha256"] = "x" * 64
    else:
        report["cleanup_status"] = "RETAINED"
    with pytest.raises(RuntimeError):
        power_gate.validate_report(report, "empty_start")
