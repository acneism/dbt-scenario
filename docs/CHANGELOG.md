# Changelog

## 0.1.0a6 — November 3, 2026

- Compile and audit every step before running its model; resolve CTE/subquery scopes and allow only mapped fixtures plus an incremental target.
- Reject external/unqualified table references, writes, locks, table functions and unsupported query grammar with redacted diagnostics.
- Recheck run-compiled SQL and retain safe audit hashes/counts in reports.
- Add a Docker acceptance job that runs the installed demo and PostgreSQL with external networking disabled.
- Add unit/query-scope cases and real dbt tests that verify forbidden relations fail before model execution.

## 0.1.0a5 — November 3, 2026

- Bind dbt manifests and run-results to the current subprocess using invocation IDs and timestamp windows; reject replayed, mismatched and malformed artifacts.
- Require exactly one successful selected model and reject forced full-refresh flags before assertions.
- Include the verified invocation ID in execution evidence and refuse existing artifact directories.
- Parse preflight with initial-step vars so required model vars work without artificial project defaults.
- Added fault-injection cases for real dbt results, full-refresh and rebuilt targets, independent-scenario continuation, multi-input rollback, report redaction and controlled model time.
- Expanded invalid-expected-fixture and reproducibility-fingerprint coverage.

## 0.1.0a4 — November 3, 2026

- Fixed validation of high-precision numeric fixtures independently of Python's global Decimal context.
- Reject timestamps with more than six fractional digits instead of silently truncating them.
- Enforce exact text/key comparison even with nondeterministic model collations.
- Cache fixture snapshots per scenario load while preserving independent mutable input/expected rows and exact byte hashes.
- Use the accelerated safe YAML loader when available, retaining alias/duplicate-key checks and enforcing a nesting limit.
- Expanded PostgreSQL acceptance cases and added a reproducible full-scenario benchmark.

## 0.1.0a3 — November 3, 2026

- Added `init --demo` with packaged example resources and `init` templates for existing dbt projects, without database access or file overwrites.
- Added an explicit `env_allowlist` for project variables; runner, connection and process controls remain reserved. Cleanup works without project-only variables.
- Added offline dependency preflight checks and safe, actionable error diagnostics with field paths or YAML line/column positions.
- Added tests for generated projects, rollback on initialization failure, environment isolation, dependency checks and redaction of invalid values.

## 0.1.0a2 — November 3, 2026

- Added atomic, password-free run journals and `cleanup --run-id` for abandoned schemas.
- Added per-run database locks, complete ownership validation and transactional restricted drops.
- Added `--keep-on-failure` to preserve database tables for debugging without marking failed tests successful.
- Applied shared deadlines to fixture updates, dbt execution, assertions and snapshot creation, with cancellation of PostgreSQL queries and dbt processes.
- Added recovery, concurrency, deadline and interruption tests. Reports now include the PostgreSQL server version and a separate cleanup reason code.

## 0.1.0a1 — November 2, 2026

- Added typed YAML scenarios, fixture routing, real PostgreSQL incremental materializations, final-state assertions and CI reports.
