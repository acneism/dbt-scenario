import copy
import importlib
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def antijoin_gate(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("check_external_antijoin")


def correction_report():
    return {
        "overall_status": "FAIL",
        "reason_code": None,
        "cleanup_status": "CLEANED",
        "steps": [
            {
                "status": "FAIL" if index else "PASS",
                "actual_rows": 2,
                "reason_code": "ROWS_MISMATCH" if index else None,
                "diff_counts": {"missing": 0, "unexpected": 0, "changed": index},
                "sql_audit": {"status": "PASS"},
                "observed_mode_evidence": {
                    "operation": "delete+insert" if index else "create_table",
                    "statement_sha256": "a" * 64,
                    "invocation_id": str(uuid.uuid4()),
                },
            }
            for index in [0, 1]
        ]
        + [{"status": "NOT_RUN", "reason_code": "PREVIOUS_STEP_UNSUCCESSFUL"}],
    }


def test_external_update_requirement_accepts_only_the_expected_changed_row(antijoin_gate):
    antijoin_gate.validate_report(correction_report(), "update_required")


@pytest.mark.parametrize(
    "fault",
    ["execution_error", "wrong_assertion", "missing_row", "no_audit", "full_refresh", "cleanup"],
)
def test_external_update_requirement_does_not_count_other_failures_as_detection(
    antijoin_gate, fault
):
    report = copy.deepcopy(correction_report())
    if fault == "execution_error":
        report.update(overall_status="ERROR", reason_code="DATABASE_ERROR")
    elif fault == "wrong_assertion":
        report["steps"][1]["reason_code"] = "SCHEMA_MISMATCH"
    elif fault == "missing_row":
        report["steps"][1]["diff_counts"] = {"missing": 1, "unexpected": 0, "changed": 0}
    elif fault == "no_audit":
        report["steps"][1]["sql_audit"]["status"] = "ERROR"
    elif fault == "full_refresh":
        report["steps"][1]["observed_mode_evidence"]["operation"] = "create_table"
    else:
        report["cleanup_status"] = "RETAINED"
    with pytest.raises(RuntimeError):
        antijoin_gate.validate_report(report, "update_required")
