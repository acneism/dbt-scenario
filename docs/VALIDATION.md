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
