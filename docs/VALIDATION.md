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

## Data precision and acceptance validation

Alpha 4 was checked on November 3, 2026 using the same local engine versions. The final suite contains 125 tests. Before the accelerated YAML parser change, the local full suite passed 120 tests with three platform-specific skips. After that change, the unit suite passed 74 tests with two skips, and all 21 direct PostgreSQL comparison tests passed. The [final Linux CI run](https://github.com/acneism/dbt-scenario/actions/runs/41534320801) passed all 125 tests for commit 1c8a295.

New cases cover high-precision decimals, rejected rounding and sub-microsecond timestamps, YAML fixture caching and independent rows, duplicate/alias/depth validation and the pure-Python parser fallback. PostgreSQL checks cover empty inputs, NULLs, compound keys, nondeterministic collations, schema changes, valid append, multiple inputs and recovery after cleanup failure. The coverage table in [ACCEPTANCE.md](ACCEPTANCE.md) records remaining gaps rather than treating the complete MVP matrix as satisfied.

The final parser also completed 20 benchmark samples, comprising 60 real dbt invocations on a ten-column workload with 10,000 initial rows. Every sample passed exact assertions and cleanup. Local Windows P50 was 50.437 s and P95 was 54.132 s; see [the protocol, limitations and raw results](BENCHMARK.md). The benchmark source hashes matched the published source bytes before Git newline normalization.

## Current-invocation and failure-boundary validation

Alpha 5 was checked on November 3, 2026 with the same engine versions. The final suite contains 184 tests. Local Windows unit checks passed 121 tests with two platform-specific skips. Fourteen selected PostgreSQL/dbt integration cases passed; the complete integration suite is delegated to the final Linux CI run rather than described as a full local rerun.

Fault injection modifies real dbt results after execution: stale timestamps, mismatched invocation IDs, a removed file and a skipped model must produce ERROR with dependent steps NOT_RUN and schemas cleaned. Additional cases force CLI/config full refresh, delete execution SQL or replace the target with an equal-valued table under a different OID. A successful-looking artifact cannot override a nonzero dbt exit.

The CLI continuation test fails the first scenario, runs a second independent scenario successfully and still exits nonzero. Synthetic email/key values remain absent from JSON, Markdown, JUnit and console output. A failure after loading the second input is rolled back for both inputs; retained tables are inspected and then explicitly cleaned.

The controlled-time scenario requires an as_of var even during parsing, filters future events across three dbt invocations and fails when a later step omits that required var. Independent unit cases cover malformed expected fixtures, each project/scenario fingerprint input and preservation of the original project during copying and mapping.

Ruff checks, formatting, source comment/docstring checks and offline wheel/source builds passed. The published performance dataset still describes alpha 4; no alpha 5 timing claim is made. The [final alpha 5 Linux CI run](https://github.com/acneism/dbt-scenario/actions/runs/41540078132) passed all 184 tests for commit 99794e1.

## SQL relation and offline acceptance validation

Alpha 6 was checked locally on November 3, 2026. The suite contains 229 tests: 160 unit cases and 69 PostgreSQL/dbt cases. Local Windows unit checks passed 158 cases with two platform-specific skips. Eleven selected real-db cases cover merge/update/retry, direct/nested/macro-generated/later-step external relations, an unsupported table function, CTE resolution, the two SQL/snapshot deadline cases and later vars that attempt hooks/custom strategies. The complete suite and the separate offline container job require the final GitHub Actions result.

SQLGlot 30.27.0 is the new pinned parser dependency. The parser's supported PostgreSQL query subset is checked before each dbt run and again against its run-compiled query. Test spies require zero model runs for forbidden first-step relations, and only the initial model run when a later step introduces an external relation. Parser diagnostics are checked for SQL/value redaction. This does not audit arbitrary Jinja execution or user-defined scalar-function behavior; see [the declared boundary](SQL-AUDIT.md).

The offline image installs Python/package dependencies during build, then runs as an unprivileged OS user with `--network none`. Its acceptance program requires only loopback interfaces, blocked external IPv4/IPv6 connections, a fresh PostgreSQL cluster, the installed package's generated demo, successful 2/3/3 final-table row counts and no leftover run schemas. Local Docker is unavailable, so no local offline-container result is claimed. [The workflow and protocol](OFFLINE.md) must pass in CI.

The first alpha 6 offline job passed for e4a3475 on PostgreSQL 16.15 with all three steps PASS and CLEANED. The final configuration-guard revision must also pass both CI jobs before being considered verified.

Per-step compilation changes the workload and uses the original shared deadlines. The slow-query and snapshot test budgets increased to 24 seconds so their intended injected delay remains reachable. Alpha 4 performance measurements remain historical, and the benchmark protocol now records the three extra compile calls, auditing and parser version.
