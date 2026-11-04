# Changelog

## Unreleased

- Reject files passed as `--scenario-dir` and directories passed as `--scenario`/`--config` before configuration loading; prevent a mistaken directory argument from silently reducing a mixed selection.
- Cover mixed file/directory selections, resolved-path deduplication and exclusion of nested fixture files.
- Report known custom routing, incremental-strategy and materialization macro blockers during metadata discovery and initialization, before fixture authoring or file writes.
- Share macro eligibility checks with execution preflight and provide an actionable `CUSTOM_MACRO_UNSUPPORTED` hint.
- Cover project/package overrides, supported business and built-in macros, malformed entries and a real dbt-generated manifest with no database access during metadata checks.
- Propagate offline Docker and acceptance failures through the CI artifact-capture pipeline by explicitly selecting Bash with `pipefail`.

## 0.1.0a10 — November 3, 2026

- Fix the example and packaged demo SQL dropping the first incoming batch after an empty initial table: use PostgreSQL timestamp `-infinity` for a NULL watermark.
- Include an explicit empty-start scenario in both example copies, preserving initial/update/retry coverage.
- Run the example unchanged in regression tests for delete+insert and merge with modern and pre-1900 timestamps.
- Verify the packaged empty-start scenario on both platforms and in the network-isolated acceptance job.

## 0.1.0a9 — November 3, 2026

- Add read-only `discover` to list root-project incremental models and their first template-initialization blocker from local manifest/catalog metadata.
- Separate ready metadata, missing column types, missing assertion keys, reserved default scenario filenames and unsupported configurations.
- Share metadata loading and eligibility checks with `init`; read each artifact once per inventory.
- Check discovery through the installed CLI and against real PostgreSQL dbt docs artifacts without database access during discovery.

## 0.1.0a8 — November 3, 2026

- Add static `validate` for YAML, fixtures, keys and step references without credentials, a dbt profile or database access.
- Identify unfinished inline and external-fixture row placeholders with a dedicated redacted diagnostic and an explicit row-list hint.
- Keep placeholder-like text inside actual data cells valid.
- Preserve word boundaries when normalizing metadata types so misspellings cannot silently become accepted PostgreSQL type names.
- Validate the installed demo without password variables before PostgreSQL startup in the network-isolated acceptance job.

## 0.1.0a7 — November 3, 2026

- Initialize scenario identifiers, column types and keys from local dbt manifest/catalog metadata without database access.
- Require explicit fixture and expected-row lists; unfinished templates cannot pass as empty scenarios.
- Preserve existing runner configuration and support separately named cases for the same model.
- Reject incompatible types, incomplete or mismatched metadata, unsafe output names and unsupported model configurations before writing.
- Verify initialization against a real PostgreSQL dbt catalog, followed by explicit fixture edits and a successful materialized scenario.

## 0.1.0a6 — November 3, 2026

- Publish the first GitHub prerelease with a wheel, source archive, dependency constraints, SHA-256 checksums and installed-package verification on Linux and Windows.
- Compile and audit every step before running its model; resolve CTE/subquery scopes and allow only mapped fixtures plus an incremental target.
- Reject external/unqualified table references, writes, locks, table functions and unsupported query grammar with redacted diagnostics.
- Recheck run-compiled SQL and retain safe audit hashes/counts in reports.
- Recheck supported model configuration after compilation so later-step vars cannot introduce hooks or custom strategies before model execution.
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
