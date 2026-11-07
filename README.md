# Controlled CI consumer

Synthetic consumer of the published dbt-scenario package and pinned reusable workflow. This branch contains no tool runtime or contributor scripts. It is a controlled author-run check, not an external-team pilot.

The runner configuration deliberately names an unreachable database. The reusable workflow must replace it with its disposable PostgreSQL service.
