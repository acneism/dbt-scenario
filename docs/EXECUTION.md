# Execution evidence

An assertion can pass only after the runner verifies the dbt execution that produced the table. It uses a new artifact directory for every subprocess and refuses to reuse an existing directory.

The supported dbt Core 1.11 artifacts are manifest v12 and run-results v6. Both need valid UUID invocation identifiers and timezone-aware invocation/generated timestamps within the runner's subprocess time window. The run-results identifier must match the manifest identifier; a previously seen invocation identifier cannot be reused for another subprocess.

The runner rechecks run-results before examining the table. It requires exactly one result, for the selected model, with status `success`. Missing, malformed, stale, mismatched, skipped and failed results produce ERROR. A successful-looking result cannot override a nonzero dbt exit code. An explicit full-refresh flag is rejected; dbt's omitted or null default and explicit false are supported.

For an initial run, the target must be absent beforehand and the emitted execution SQL must create a table. For an incremental run, the target must keep its PostgreSQL OID and the emitted SQL must include the expected append, delete+insert or merge operation. A changed model configuration, rebuilt target, missing SQL or unknown mode produces ERROR before data assertions can pass.

Reports include the verified invocation ID, operation, verification method and SQL SHA-256, without SQL text, fixture values, connection settings or raw dbt diagnostics. Files in dbt's temporary project are removed after the run. Ownership journals support database cleanup after a process is interrupted; the execution artifacts are not recovery credentials.

These checks detect stale or inconsistent evidence from a trusted local project. They are not an attestation system for malicious code that fabricates artifacts. Wall-clock corrections during a subprocess can cause a safe refusal with DBT_ARTIFACT_STALE; rerun after stabilizing the clock.
