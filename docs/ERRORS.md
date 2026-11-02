# Common errors

| Code | Correction |
|---|---|
| INIT_WOULD_OVERWRITE | Select a new destination or preserve existing files before initialization. |
| DBT_PROJECT_NOT_FOUND | Point project_dir at the folder containing dbt_project.yml. |
| MISSING_PASSWORD_ENV | Export the variable named in database.password_env. |
| MISSING_PROJECT_ENV | Export every variable named in env_allowlist. |
| INVALID_ENV_ALLOWLIST | Use distinct variable names and remove reserved runtime controls. |
| DEPENDENCIES_NOT_INSTALLED | Run dbt deps in the original project and retry. |
| UNSUPPORTED_DEPENDENCY_LOCATION | Keep installed packages inside the project, outside build/artifact directories. |
| MODEL_NOT_FOUND | Replace the template model with its real model.project.name unique_id. |
| INPUT_DEPENDENCIES_MISMATCH | Supply one fixture for each direct source() or ref() dependency. |
| INVALID_SCENARIO_SCHEMA | Check the indicated field against the version 1 scenario schema. |
| INVALID_TYPED_VALUE | Match the declared column type; quote decimal and timestamp values. |
| FIXTURE_COLUMNS_MISMATCH | Include every declared column exactly once in each row. |
| INVALID_RUN_VARS | Use JSON-compatible vars without non-finite numbers or binary values. |
| INVALID_EXPECTED_KEY | Expected keys must be non-null and unique. |
| RUN_STILL_ACTIVE | Wait for the active run before invoking cleanup. |
| STEP_TIMEOUT | Increase step_timeout or reduce that step's work. |
| SCENARIO_TIMEOUT | Increase scenario_timeout or reduce setup and scenario work. |

For example, a bad typed value can produce:

```text
ERROR INVALID_TYPED_VALUE at $.steps[1].inputs[*].replace.rows[2][*]
  Match the declared column type; quote decimals and timestamps.
```

The path identifies the third row of the second step. Mapping names are masked to keep arbitrary keys out of diagnostics. Values are never included in these messages. YAML syntax errors instead report one-based line and column positions.

Execution errors keep stable reason codes and safe hints in summary JSON. They do not include raw SQL, credentials or exception text. A generic DBT_EXECUTION_ERROR can also mean a project compilation/runtime error that the preflight checks cannot classify.
