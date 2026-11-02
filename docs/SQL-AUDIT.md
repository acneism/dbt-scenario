# Compiled SQL relation checks

Every step invokes `dbt compile` after its fixtures are loaded and before invoking `dbt run`. The compilation uses that step's vars and current target state. The runner parses the selected model's compiled query with SQLGlot's PostgreSQL dialect and resolves tables through query scopes, including CTEs and subqueries. SQLGlot is pinned to 30.27.0 because the grammar and strict parser fallback are part of this check. See the [SQLGlot AST and scope documentation](https://github.com/tobymao/sqlglot/blob/main/posts/ast_primer.md).

Allowed physical relations are the generated input tables for the current scenario. Incremental steps also allow the current target. References need an explicit schema and, if supplied, the current database name. CTE names are resolved in their own scopes, with PostgreSQL identifier folding and quoted-name semantics.

An external table, cross-database name, ambiguous unqualified name or undeclared generated table returns SQL_EXTERNAL_RELATION before the model's `run` command. The query must be a single SELECT/set operation of at most 1 MiB. Writes, SELECT INTO, locks, table-valued functions, LATERAL relations and unsupported grammar return SQL_AUDIT_UNSUPPORTED. There is no fallback to a regex-based allow decision. Parse errors and parser fallback diagnostics do not print SQL.

The runner also audits the compiled query returned by `dbt run`. Reports retain pre-run and run-compiled query hashes, the number of checked physical references and the audit method, without relation names or query text. `plan` checks declared dependencies through parsing; relation auditing takes place during `test`, when fixtures and target state are available.

Every compiled step also rechecks supported model configuration. Vars cannot introduce hooks, grants, persist_docs, an enforced contract, a custom strategy or non-SQL language on a later step and proceed to model execution. Routing and materialization must remain valid for the selected isolated target.

Compilation adds a dbt subprocess to each step and consumes the existing step/scenario deadline. Alpha 4's timings do not measure this version. Existing snapshot and slow-query tests have larger budgets to allow the extra compilation to finish before injecting their intended delay.

This is a diagnostic check for trusted local projects, not a sandbox. dbt Jinja, `run_query`, introspective macros and user-defined scalar functions can execute code outside the compiled SELECT's table references. Compilation and execution can also render different SQL. Do not attach production data or credentials to the disposable test database; its permissions remain the isolation boundary. Custom hooks/materializations/routing macros remain unsupported. The audit does not prove that arbitrary macros or functions have no side effects.
