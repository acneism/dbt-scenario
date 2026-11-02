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

The remaining MVP work is:

- Remaining acceptance-matrix cases, including schema/type variations and complete data edge cases.
- Performance measurements and comparison against hand-written dbt scripts and existing audit packages.
- External pilots showing that teams retain the tests in CI and can add their second scenario independently.

The next adapter should be selected with a concrete pilot user. Local PostgreSQL results do not validate Snowflake or BigQuery behavior.
