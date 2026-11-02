# Roadmap

The first alpha implements the vertical path: typed input snapshots, a real dbt incremental model, exact final-state assertions, retries, isolated schemas and CI reports.

The complete MVP still needs:

- Coverage for the entire acceptance matrix, including concurrent processes and controlled interruptions.
- Durable resource ownership journals and explicit cleanup of abandoned runs.
- Complete per-step deadlines covering fixture loading, comparison and snapshot creation.
- A supported project environment-variable allowlist and improved dependency diagnostics.
- A user-facing `init` command and actionable, safe validation diagnostics.
- Performance measurements and comparison against hand-written dbt scripts and existing audit packages.
- External pilots showing that teams retain the tests in CI and can add their second scenario independently.

The next adapter should be selected with a concrete pilot user. Local PostgreSQL results do not validate Snowflake or BigQuery behavior.
