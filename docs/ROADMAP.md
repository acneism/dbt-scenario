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

The remaining work is:

- Broader SQL compatibility guided by real projects, while keeping the trusted-code/disposable-database boundary explicit.
- Controlled Linux performance measurements and comparison against hand-written dbt scripts and existing audit packages.
- External pilots showing that teams retain the tests in CI and can add their second scenario independently.

The next adapter should be selected with a concrete pilot user. Local PostgreSQL results do not validate Snowflake or BigQuery behavior.
