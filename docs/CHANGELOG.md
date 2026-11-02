# Changelog

## 0.1.0a2 — November 3, 2026

- Added atomic, password-free run journals and `cleanup --run-id` for abandoned schemas.
- Added per-run database locks, complete ownership validation and transactional restricted drops.
- Added `--keep-on-failure` to preserve database tables for debugging without marking failed tests successful.
- Applied shared deadlines to fixture updates, dbt execution, assertions and snapshot creation, with cancellation of PostgreSQL queries and dbt processes.
- Added recovery, concurrency, deadline and interruption tests. Reports now include the PostgreSQL server version and a separate cleanup reason code.

## 0.1.0a1 — November 2, 2026

- Added typed YAML scenarios, fixture routing, real PostgreSQL incremental materializations, final-state assertions and CI reports.
