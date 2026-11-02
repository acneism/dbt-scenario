# Changelog

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
