# Existing approaches and validation plan

Reviewed November 3, 2026. The table records documented workflows. Setup effort and maintenance cost still require a comparison on the same real project.

| Approach | Documented workflow | Where dbt-scenario fits |
|---|---|---|
| Built-in dbt unit tests | Static input fixtures and incremental-mode overrides; expected rows describe data prepared for insertion/merge. The documentation identifies final-table materialization checks as a remaining limitation. [dbt documentation](https://docs.getdbt.com/docs/build/unit-tests#unit-testing-incremental-models) | Exercises the actual materialization and checks the entire resulting table after several runs. |
| EqualExperts dbt-unit-testing | Mocked model inputs and incremental query logic. Its README states that testing merge, delete+insert and insert_overwrite strategies is outside its supported scope. [Incremental models](https://github.com/EqualExperts/dbt-unit-testing#incremental-models) | Tests real PostgreSQL merge/delete+insert/append behavior while retaining state across steps. |
| dbt-audit-helper-ext | Sequential snapshots of source and reference mart tables, cloning prior state, an incremental build and comparison against the next reference snapshot. [Incremental workflow](https://github.com/infinitelambda/dbt-audit-helper-ext/blob/main/docs/validation-incremental-load.md) | Provides a fixture-first runner with named steps and retry expectations; the underlying validation task already has an open-source solution. |
| dbt-audit-helper-ext platform support | Its README lists PostgreSQL as well as several other engines, and documents adapter-specific limits for schema checks. [Project README](https://github.com/infinitelambda/dbt-audit-helper-ext) | Currently supports only PostgreSQL 16, with a deliberately narrow type/configuration boundary. |
| Hand-written dbt CLI/pytest harness | Baseline to implement: fixture loading, sequential dbt invocations and exact final-table assertions. | Packages isolation, deadlines, recovery and reporting so those behaviors can be reused. |

The product hypothesis is convenience for small, repeatable materialization tests in an existing project. The materialization and table-comparison capabilities themselves are not unique.

Before expanding the adapter list, compare the same late-arrival and retry scenario through a manual harness, audit-helper-ext and dbt-scenario. Record setup time, project edits, test-specific code, diagnostic clarity and effort to add a second case. PostgreSQL schema-addition and numeric-scale cases should also be compared explicitly.

The existing local performance result describes dbt-scenario alone. It does not establish a speed or setup advantage over another approach. The strongest adoption signal remains external teams keeping these scenarios in CI and independently adding their next test.

[Recorded synthetic comparison results](EVALUATION-RESULTS.md) now cover five cases and two native-dbt experiments. They show that manual and package-based gates detect the materialization bugs too; the comparison does not establish an onboarding or adoption advantage.
