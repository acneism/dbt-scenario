# November 2026 audit corrections

Alpha13 addresses the seven findings recorded against alpha12 source `fbeb3bce24aee4102a86f04cb3d02dcedcdd0544`. The original audit is a record of that version; passing the older suite did not cover these counterexamples.

| Finding | Correction | Regression coverage |
| --- | --- | --- |
| F01: SQL injected through model configuration escaped relation checking | Nonempty `sql_header`, `incremental_predicates` and `predicates` are refused in metadata/preflight and per-step checks | Metadata refuses before writing; real PostgreSQL tests require refusal before materialization and after a later vars change |
| F02: Windows descendant survived after its parent exited | A launcher waits until it belongs to a Windows Job Object before starting the command; closing the job terminates descendants | Real Windows tests cover both living and already-exited parent processes, plus preservation of command exit codes |
| F03: ignored `.venv` was still scanned for symlinks | Directory scanning, copying and fingerprinting share exclusions | Portable scan/copy tests plus a real symlink test on systems permitting link creation; links in copied model files remain refused |
| F04: vulnerable development pytest dependency | Dev range and lock use pytest 9.0.3 or later in the supported major version | Unit suite runs with pinned pytest 9.0.3; runtime installs do not install pytest |
| F05: CI lost ERROR counts for real cleanup statuses | Summary accepts runner terminal values `NOT_NEEDED`, `ERROR`, `KEPT`, `CLEANED` | Executes the workflow's actual summary code with error reports and checks counts, validity and preserved exit 2 |
| F06: demo teardown left an anonymous PostgreSQL volume | Quickstart uses `docker compose down --volumes` | Documentation matches the image's volume behavior; Docker teardown was not dynamically reexecuted locally |
| F07: project fingerprint serialization was ambiguous | Hash input uses a version marker, length-prefixed UTF-8 paths and fixed-size file digests | The two audit trees now produce different fingerprints |

## Compatibility and report changes

Models using nonempty SQL configuration listed above now receive `MODEL_SQL_CONFIG_UNSUPPORTED` before running. A later configuration change receives `MODEL_CONFIGURATION_CHANGED`. These settings are deliberately outside the supported SELECT audit; ordinary filters inside the model SELECT remain supported. See [SQL auditing](SQL-AUDIT.md).

New reports include `project_hash_format: 2`. The SHA-256 field remains a hexadecimal string, but its value changes for the same project because the framing has changed. Alpha12 and earlier project hashes should be compared only within their original format. Scenario and fixture hash formats are unchanged. Old JSON reports remain readable.

Windows execution uses an anonymous, noninheritable Job Object with kill-on-close. The waiting launcher prevents the command from spawning before assignment. If job creation or assignment is unavailable, execution refuses with `PROCESS_ISOLATION_FAILED`; it does not run the command with partial process control. This uses the Windows [job inheritance and lifetime semantics](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

The pytest fix addresses [CVE-2025-71176](https://github.com/pytest-dev/pytest/releases/tag/9.0.3), a development/test-environment issue involving temporary directories on Unix. It is separate from runtime CLI behavior.

The [pilot protocol](PILOT.md) now matches the original four-week retention criterion, with a two-week feedback checkpoint. This is a criterion for a future pilot, not an observed adoption result.

## Running the regressions

```sh
python -m pytest tests/test_audit_regressions.py tests/test_lifecycle.py tests/test_scaffold.py
python -m pytest -m integration -k 'model_sql_configuration or later_unsupported or real_incremental_update_late_arrival_retry'
```

The integration command needs the documented restricted PostgreSQL 16 test role and disposable database. The repository CI runs all unit and integration tests on Linux, the offline demo and a Windows unit job. Actual release validation and exact source/run identifiers are recorded in the [release checks](RELEASING.md).

## Recorded verification

Checked November 17, 2026 for source `f94f1127e2e2c506663e497ee7d91947cf3e998e`. The [full CI](https://github.com/acneism/dbt-scenario/actions/runs/44115416096) passed 406 Linux unit tests and all 97 PostgreSQL integration tests, offline acceptance, and 407 Windows unit tests. The platform-specific skips are reported by each job; these counts are not a sum of distinct cross-platform test cases. The Windows GitHub runner executed both real symlink checks and the descendant-lifetime checks.

Eight targeted PostgreSQL tests also passed locally on Windows: normal incremental strategies, refusal of initial SQL configuration and refusal after a later vars change. The exact [CI wheel and sdist](https://github.com/acneism/dbt-scenario/actions/runs/44115416329) passed fresh installed-package verification on Linux and Windows, including both ordinary and empty-start demos. All 32 packaged runtime/resource files match source. All five [external-model checks](https://github.com/acneism/dbt-scenario/actions/runs/44115416031) passed.

The published [alpha13](https://github.com/acneism/dbt-scenario/releases/tag/v0.1.0a13) assets were downloaded anonymously and matched all seven verified files. A fresh public-URL installation matched all 32 package files, validated both demo definitions without a database password, refused the three SQL configuration names and preserved process exit codes. Its [installation report](distribution/v0.1.0a13-install.json) distinguishes that static check from the separate database verification.

The current [workflow controls](evaluation/audit-fixes-alpha13-controls.json) confirm two PASS/CLEANED reports and, separately, two early ERROR/NOT_NEEDED reports with CLI exit 2. This is technical validation by the author, not external adoption. The [validation index](evaluation/audit-fixes-alpha13.json) links the evidence and records the limits of Docker teardown and dependency checks.
