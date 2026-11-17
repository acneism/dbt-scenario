import json
import pathlib
from typing import Literal, NotRequired, TypedDict
from xml.etree import ElementTree

ScenarioStatus = Literal["PASS", "FAIL", "ERROR"]
CleanupStatus = Literal["CLEANED", "KEPT", "ERROR", "NOT_NEEDED"]
RunMode = Literal["initial", "incremental"]
ErrorStage = Literal["setup", "step", "workspace_cleanup"]


class DiffCounts(TypedDict):
    missing: int
    unexpected: int
    changed: int


class ComparisonResult(TypedDict):
    status: Literal["PASS", "FAIL"]
    reason_code: str | None
    diff_counts: DiffCounts | None
    actual_rows: int | None
    expected_rows: int | None
    changed_columns: list[str]


class StepSummary(TypedDict):
    name: str
    status: ScenarioStatus | Literal["NOT_RUN"]
    reason_code: str | None
    duration_ms: int
    requested_mode: NotRequired[RunMode]
    observed_mode: NotRequired[RunMode | None]
    observed_mode_evidence: NotRequired[dict[str, str] | None]
    sql_audit: NotRequired[dict[str, str | int] | None]
    diff_counts: NotRequired[DiffCounts | None]
    actual_rows: NotRequired[int | None]
    expected_rows: NotRequired[int | None]
    changed_columns: NotRequired[list[str]]


class ScenarioReport(TypedDict):
    schema_version: Literal[1]
    run_id: str
    scenario: str
    model_unique_id: str
    scenario_hash: str
    fixture_hashes: dict[str, str]
    project_hash: str | None
    project_hash_format: Literal[2]
    project_env_names: list[str]
    started_at: str
    duration_ms: int
    engine_versions: dict[str, str | int]
    overall_status: ScenarioStatus
    cleanup_status: CleanupStatus
    cleanup_reason_code: str | None
    reason_code: str | None
    steps: list[StepSummary]
    diagnostic: NotRequired[dict[str, str | int | None]]
    error_stage: NotRequired[ErrorStage]


def reason_lines(report: ScenarioReport) -> list[str]:
    lines = []
    if reason := report.get("reason_code"):
        lines.append(f"Scenario reason: {reason}")
    if cleanup_reason := report.get("cleanup_reason_code"):
        lines.append(f"Cleanup reason: {cleanup_reason}")
    if stage := report.get("error_stage"):
        lines.append(f"Error stage: {stage}")
    return lines


def write_report(report: ScenarioReport, directory: pathlib.Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    steps = report["steps"]
    suite = ElementTree.Element(
        "testsuite", name=report["scenario"], tests=str(max(1, len(steps)))
    )
    for step in steps:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            name=step["name"],
            classname=report["scenario"],
            time=str(step.get("duration_ms", 0) / 1000),
        )
        status = step["status"]
        if status in {"FAIL", "ERROR"}:
            ElementTree.SubElement(
                case,
                "failure" if status == "FAIL" else "error",
                message=step["reason_code"] or status,
            )
        elif status == "NOT_RUN":
            ElementTree.SubElement(
                case, "skipped", message="PREVIOUS_STEP_UNSUCCESSFUL"
            )
    if report["overall_status"] == "ERROR" and not any(
        s["status"] == "ERROR" for s in steps
    ):
        case = ElementTree.SubElement(
            suite, "testcase", name="scenario_setup_or_cleanup"
        )
        ElementTree.SubElement(
            case, "error", message=report["reason_code"] or "SCENARIO_ERROR"
        )
    suite.set("tests", str(len(suite)))
    suite.set("failures", str(sum(len(c.findall("failure")) for c in suite)))
    suite.set("errors", str(sum(len(c.findall("error")) for c in suite)))
    suite.set("skipped", str(sum(len(c.findall("skipped")) for c in suite)))
    (directory / "junit.xml").write_bytes(
        ElementTree.tostring(suite, encoding="utf-8", xml_declaration=True)
    )
    lines = [f"Result: {report['overall_status']}", ""]
    if reasons := reason_lines(report):
        lines.extend(f"- {line}" for line in reasons)
        lines.append("")
    lines.extend(["| Step | Status | Reason |", "|---|---|---|"])
    for step in steps:
        lines.append(
            f"| {step['name']} | {step['status']} | "
            f"{step.get('reason_code') or ''} |"
        )
    (directory / "summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
