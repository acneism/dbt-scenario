import json
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring


def write_report(report: dict, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    steps = report["steps"]
    suite = Element("testsuite", name=report["scenario"], tests=str(max(1, len(steps))))
    for step in steps:
        case = SubElement(
            suite,
            "testcase",
            name=step["name"],
            classname=report["scenario"],
            time=str(step.get("duration_ms", 0) / 1000),
        )
        status = step["status"]
        if status in {"FAIL", "ERROR"}:
            SubElement(
                case,
                "failure" if status == "FAIL" else "error",
                message=step["reason_code"] or status,
            )
        elif status == "NOT_RUN":
            SubElement(case, "skipped", message="PREVIOUS_STEP_UNSUCCESSFUL")
    if report["overall_status"] == "ERROR" and not any(s["status"] == "ERROR" for s in steps):
        case = SubElement(suite, "testcase", name="scenario_setup_or_cleanup")
        SubElement(case, "error", message=report["reason_code"] or "SCENARIO_ERROR")
    suite.set("tests", str(len(suite)))
    suite.set("failures", str(sum(len(c.findall("failure")) for c in suite)))
    suite.set("errors", str(sum(len(c.findall("error")) for c in suite)))
    suite.set("skipped", str(sum(len(c.findall("skipped")) for c in suite)))
    (directory / "junit.xml").write_bytes(tostring(suite, encoding="utf-8", xml_declaration=True))
    lines = [
        f"Result: {report['overall_status']}",
        "",
        "| Step | Status | Reason |",
        "|---|---|---|",
    ]
    for step in steps:
        lines.append(f"| {step['name']} | {step['status']} | {step.get('reason_code') or ''} |")
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
