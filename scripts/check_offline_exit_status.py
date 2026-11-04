import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from shlex import quote

import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--bash", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    args = parser.parse_args()
    workflow_path = args.repo / ".github/workflows/ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"]["offline"]["steps"]
        if step.get("name") == "Run demo without external networking"
    )
    expected_shell = None if args.phase == "before" else "bash"
    if step.get("shell") != expected_shell:
        raise SystemExit("UNEXPECTED_WORKFLOW_SHELL")
    shell_flags = ["-e"] if expected_shell is None else ["--noprofile", "--norc", "-eo", "pipefail"]
    environment = dict(os.environ)
    for name in ["BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS"]:
        environment.pop(name, None)
    environment["PATH"] = str(args.bash.parent.parent / "usr/bin") + os.pathsep + environment["PATH"]
    cases = [
        ("success", 0, '{"status":"PASS"}', False, 0),
        ("acceptance_failure", 2, "", False, 2),
        ("docker_failure", 125, "", False, 125),
        ("failure_after_pass_output", 17, '{"status":"PASS"}', False, 17),
        ("terminated_producer", 137, "", False, 137),
        ("artifact_write_failure", 0, '{"status":"PASS"}', True, 73),
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=args.phase + "-", dir=args.output))
    results = []
    for name, producer_status, payload, tee_failure, expected in cases:
        case_root = root / name
        case_root.mkdir()
        standin = "docker() {\n"
        if payload:
            standin += "printf '%s\\n' " + quote(payload) + "\n"
        standin += f"return {producer_status}\n}}\n"
        if tee_failure:
            standin += "tee() { cat > /dev/null; return 73; }\n"
        (case_root / "step.sh").write_text(standin + step["run"], encoding="utf-8")
        result = subprocess.run(
            [str(args.bash), *shell_flags, "step.sh"],
            cwd=case_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.stderr:
            raise SystemExit("UNEXPECTED_SHELL_STDERR_" + name.upper())
        masked = expected != 0 and result.returncode == 0
        if args.phase == "after" and result.returncode != expected:
            raise SystemExit("FAILURE_PROPAGATION_MISMATCH_" + name.upper())
        if args.phase == "before" and result.returncode != (73 if tee_failure else 0):
            raise SystemExit("BASELINE_MISMATCH_" + name.upper())
        report_path = case_root / "artifacts/offline/result.json"
        results.append(
            {
                "case": name,
                "producer_exit": producer_status,
                "expected_exit": expected,
                "observed_exit": result.returncode,
                "failure_masked": masked,
                "result_file_exists": report_path.exists(),
                "result_file_bytes": report_path.stat().st_size if report_path.exists() else None,
            }
        )
    report = {
        "status": "PASS",
        "date": "2026-11-04",
        "phase": args.phase,
        "scope": "Exact offline workflow run body with synthetic docker and failing tee shell functions; no container or database executed",
        "bash_version": subprocess.run(
            [str(args.bash), "--version"], check=True, capture_output=True, text=True
        ).stdout.splitlines()[0],
        "workflow_shell": expected_shell,
        "shell_flags": shell_flags,
        "run_body_sha256": hashlib.sha256(step["run"].encode()).hexdigest(),
        "cases": results,
        "masked_failures": sum(case["failure_masked"] for case in results),
    }
    path = args.output / (args.phase + ".json")
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.phase == "after":
        before = json.loads((args.output / "before.json").read_text(encoding="utf-8"))
        if before["run_body_sha256"] != report["run_body_sha256"]:
            raise SystemExit("WORKFLOW_RUN_BODY_CHANGED")
        if before["masked_failures"] != 4 or report["masked_failures"] != 0:
            raise SystemExit("UNEXPECTED_MASKED_FAILURE_COUNT")
        comparison = {"status": "PASS", "before": before, "after": report}
        (args.output / "comparison.json").write_text(
            json.dumps(comparison, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"phase": args.phase, "cases": len(results), "masked_failures": report["masked_failures"], "status": "PASS"}))


if __name__ == "__main__":
    main()
