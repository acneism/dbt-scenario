# Acceptance coverage

This maps the original A01–A30 requirements to executable checks. Passing the automated suite is separate from demonstrating usefulness in external projects. A partial item is not considered completed acceptance.

| Requirement | Coverage | Evidence |
|---|---|---|
| A01–A05: initial load, updates, strategies, late events, retries | Covered | Real dbt integration scenarios for delete+insert and merge; wrong-watermark negative case |
| A06–A07: append semantics | Covered | Duplicate-key failure and a successful append with disjoint incoming batches |
| A08–A10: exact values, unchanged aggregates, NULL and decimals | Covered | Equal-total swaps, NULL versus zero, numeric(38,2) roundtrip and independent Decimal context |
| A11: compound keys | Covered | Real compound merge plus duplicate and NULL component failures |
| A12: invalid expected fixtures | Covered | Missing/extra columns, scalar rows, invalid containers and values, duplicate and NULL expected keys are rejected before execution |
| A13: empty versus missing tables | Covered | Packaged empty-start scenario with unchanged example SQL, delete+insert/merge and modern/pre-1900 timestamps; empty incoming batch; missing actual relation raises an error |
| A14: schema changes | Covered | Added/removed columns, changed numeric scale and a real dbt schema addition |
| A15: unchanged input state | Covered | Two direct inputs; one changes while the ref fixture persists |
| A16: unsupported and external dependencies | Covered within the declared SQL subset | Declared dependencies are checked; per-step compiled SQL permits only fixtures/current target and scoped CTEs. Direct, nested and macro-generated external tables are rejected before model run. Trusted Jinja/scalar functions are not a sandbox; see SQL-AUDIT.md |
| A17: real incremental mode | Covered | Forced CLI/config full refresh, missing execution SQL and rebuilt target all return ERROR; normal strategies retain verified evidence |
| A18: failed, missing or stale execution artifacts | Covered | Nonzero exit, skipped/duplicate/wrong results, missing/malformed files, replayed IDs, stale times and mismatched invocations cannot pass; real dbt output is fault-injected |
| A19: failed-step handling | Covered | The first scenario fails its initial assertion, later steps are NOT_RUN, an independent scenario passes and the CLI still exits nonzero |
| A20: atomic fixture updates | Covered | Failure after the second input is replaced rolls back both tables to the first snapshot; deadline cancellation also rolls back |
| A21–A24: concurrency, interruption, ownership and cleanup errors | Covered | Separate CLI processes, SIGINT, deadlines, abrupt exit recovery, ownership refusal and cleanup-failure gate |
| A25: safe reports | Covered | Synthetic email/key fixture values and a compiler message are absent from JSON, Markdown, JUnit and CLI output; database passwords are also checked |
| A26: reproducibility fingerprints | Covered | SQL, macro, project config, lock, fixture and vars changes alter the corresponding hash; project copying/mapping and real runs preserve original files |
| A27: invalid/empty selections and unsafe inputs | Covered | Empty selection, unknown schema fields, path escapes and executable YAML tags fail |
| A28: offline execution after installation | Automated CI check | A separate Docker job runs the installed demo with only loopback networking, checks blocked external IPv4/IPv6 connections and verifies PostgreSQL results/cleanup. Its final CI result must pass; see OFFLINE.md |
| A29: time values | Covered | PostgreSQL compares timestamptz instants; unsupported timezone use and sub-microsecond truncation are rejected |
| A30: controlled model time | Covered | Required as_of vars reach preflight and each step, future events remain excluded, and an omitted later var fails without inheriting earlier values; see TIME.md |

Database comparison tests use PostgreSQL 16. ICU cases explicitly create a nondeterministic collation to prove that exact comparisons still distinguish case and accents. Such cases skip only when PostgreSQL was built without ICU.

The test database and project code are trusted. Production credentials are not needed. The current tool is not an enforcement sandbox for malicious macros or arbitrary SQL side effects.
