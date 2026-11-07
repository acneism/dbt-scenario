# Roadmap

The alpha implements typed input snapshots, real dbt incremental models, exact final-state assertions, retries, isolated schemas, CI reports and recovery of abandoned runs.

Implemented in alpha 2:

- Atomic resource journals, active-run locks and explicit cleanup by run ID.
- Ownership validation before deletion and restricted drops that cannot cascade into another run.
- Retained tables for failed scenarios with `--keep-on-failure`.
- Shared step/scenario deadlines covering SQL, dbt execution and snapshot creation.
- Tests for independent CLI processes, interrupted runs, abandoned resources and query cancellation.

Implemented in alpha 3:

- Database-free initialization of a runnable demo and an existing-project scenario template.
- Explicit project environment forwarding with reserved runner controls kept separate.
- Offline checks for installed dependencies and actionable error hints.
- Safe field paths and YAML line/column diagnostics without row values.

Implemented in alpha 4:

- High-precision numeric validation, explicit timestamp precision and exact text collation semantics.
- Additional PostgreSQL cases for empty tables, NULLs, compound keys, schema changes and failed cleanup.
- A repeatable benchmark that measures complete scenarios and validates every measured result.
- An explicit acceptance-coverage table that keeps untested requirements visible.

Implemented in alpha 5:

- Current-invocation verification for dbt artifacts, replay refusal and safe execution IDs in reports.
- Fault injection for forced full refresh, rebuilt targets, missing SQL and stale/skipped dbt output.
- Independent-scenario continuation, multi-input transactional rollback and fixture-value redaction checks.
- Initial-step vars in preflight, plus a documented and tested required as_of model.
- Separate expected-fixture and project/scenario fingerprint acceptance cases.

Implemented in alpha 6:

- PostgreSQL query-scope auditing before each model run, with strict refusals for external relations and unsupported SQL.
- Real dbt tests proving direct, nested and macro-generated external relations stop before model execution.
- A Docker CI job for the installed demo with network access removed and PostgreSQL running inside the container.

Implemented in alpha 7–9:

- Manifest/catalog-based templates with explicit unfinished row lists and preservation of existing files.
- Static fixture validation without database access, including dedicated unfinished-row diagnostics.
- Read-only discovery of incremental model candidates and their first metadata/template blocker.
- Installed-package checks and public installation reports for released artifacts.

Alpha 10 fixes the packaged empty-start example. Alpha 11 adds finite double precision fixtures and [checks an unchanged public PostgreSQL demonstration model](AQW-COMPATIBILITY.md), including a composite key and three double columns. It also moves known macro refusals earlier and validates CLI selection paths. This is compatibility evidence for one selected model; setup effort and continued use by an external team are still unmeasured.

A subsequent [selected portfolio-model check](CLINICAL-COMPATIBILITY.md) exercises unchanged correlated anti-join SQL, 28 output columns and the distinction between new-key-only and update expectations. Its typed fixture contract does not validate the complete original pipeline or upstream catalog. Broader compatibility and all three remaining items stay open.

Alpha 12 adds exact unconstrained numeric fixtures, guided by an original PostgreSQL cast and seed declaration in the [power-model check](POWER-COMPATIBILITY.md). That check exercises merge, a three-column key, a seven-day revision boundary and repeated local clock times. Original transformations/packages and an upstream catalog remain outside the focused fact-model execution. This narrows a concrete compatibility gap without completing the broader compatibility or pilot items.

The [reusable GitHub Actions workflow](GITHUB-ACTIONS.md) now supplies a public-package installation and disposable test database without copying contributor scripts. A separate controlled consumer verifies exit codes 0/1/2, failure propagation, public dependency installation, reports and cleanup. These are machine-executed controls; human setup/maintenance comparison and external retention remain unmeasured.

A [first-to-second scenario rehearsal](FIRST-AND-SECOND-SCENARIO.md) now connects the installed public CLI and a real parsed manifest to two successive passing CI runs. The second commit adds only its scenario file; the first scenario, SQL, runner configuration and workflow remain unchanged. This verifies the technical addition path without completing the human comparison or external pilot items.

The remaining work is:

- Broader SQL compatibility guided by real projects, while keeping the trusted-code/disposable-database boundary explicit.
- Human setup/maintenance comparison on real projects; controlled Linux timings and synthetic manual/audit-helper-ext/native-dbt results are recorded in EVALUATION-RESULTS.md.
- External pilots showing that teams retain the tests in CI and can add their second scenario independently.

The next adapter should be selected with a concrete pilot user. Local PostgreSQL results do not validate Snowflake or BigQuery behavior.
