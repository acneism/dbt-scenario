# Initial validation

The initial alpha was checked locally on November 2, 2026:

| Component | Version |
|---|---|
| Python | 3.12.10 |
| PostgreSQL | 16.15, Windows EDB binaries |
| dbt Core | 1.11.16 |
| dbt-postgres | 1.10.2 |
| psycopg | 3.3.6 |

Results: 21 validation/CLI tests and 8 integration tests passed. Ruff checks and formatting passed. Both the source distribution and wheel built successfully; the wheel contains the scenario schema and Apache-2.0 license. Python source and test files contain no comments or docstrings.

The integration suite ran actual PostgreSQL materializations for delete+insert and merge, detected a wrong event-time watermark, rejected duplicate keys from append, detected a value swap with unchanged row count and total, routed a ref dependency to fixtures, redacted a deliberately sensitive error and checked CLI exit codes with JSON/JUnit output. The example completed all three steps and cleaned its generated schemas.

These checks do not complete the full MVP acceptance matrix or establish adoption by external teams. Linux CI is configured separately and its status must be checked after the workflow runs.

## Recovery and deadlines validation

Alpha 2 was checked on November 3, 2026 using the same local engine versions. The expanded suite contains 52 tests. Local Windows checks passed 50 tests; the POSIX process-group and SIGINT checks are reserved for Linux CI.

New integration cases cover cleanup refusal while a runner holds its lock, ownership mismatch without partial deletion, foreign view dependencies without cascading deletion, deadline cancellation with transactional rollback, slow dbt queries, snapshot deadlines, setup deadlines, repeated cleanup after a retained failure, recovery after abrupt process exit and two simultaneous CLI processes.

Ruff and the source-comment/docstring check passed. Wheel and source distributions for `0.1.0a2` built offline using cached build dependencies. The new Linux workflow run must validate the platform-specific tests before treating those cases as confirmed.

## Initialization and configuration validation

Alpha 3 was checked on November 3, 2026 using the same local engine versions. The suite contains 85 tests. Local Windows checks passed 82 tests; three cases require Linux process signals or symlink creation and are checked in CI.

New cases cover a real PostgreSQL run of the initialized demo, explicit project environment forwarding, exclusion of unlisted variables, reserved runtime controls, initialization rollback and collision handling, dependency preflight checks and redacted diagnostics for invalid rows and YAML.

The wheel was checked independently of the source checkout: its nine packaged demo resources generated a valid scenario from the installed archive. Wheel/source builds, Ruff checks and the no-comments/docstrings check passed. CI results must be checked for the final commit.
