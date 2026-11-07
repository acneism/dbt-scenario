FIELDS = {
    "version",
    "name",
    "model",
    "inputs",
    "output",
    "columns",
    "primary_key",
    "steps",
    "run",
    "mode",
    "vars",
    "expect",
    "rows",
    "fixture",
    "replace",
    "same_as",
    "node",
    "database",
    "project_dir",
    "host",
    "port",
    "dbname",
    "user",
    "password_env",
    "sslmode",
    "step_timeout",
    "scenario_timeout",
    "env_allowlist",
}

HINTS = {
    "CUSTOM_MACRO_UNSUPPORTED": (
        "Choose a project without custom routing, incremental-strategy or materialization macros."
    ),
    "UNSUPPORTED_MATERIALIZATION": "Choose an incremental model without forced full refresh.",
    "UNSUPPORTED_INCREMENTAL_STRATEGY": "Choose append, delete+insert or merge on PostgreSQL 16.",
    "MODEL_HOOKS_UNSUPPORTED": "Choose a model without hooks, grants or persisted documentation.",
    "MODEL_CONFIG_UNSUPPORTED": "Choose a SQL model without an enforced contract.",
    "INPUT_DEPENDENCY_UNSUPPORTED": "Use direct model/source inputs in the root project.",
    "EPHEMERAL_INPUT_UNSUPPORTED": "Choose a model whose direct inputs are not ephemeral.",
    "DIRECT_BUILTIN_OR_VERSIONED_REF_UNSUPPORTED": "Choose an unversioned root-project model.",
    "UNFILLED_TEMPLATE_ROWS": (
        "Replace this rows placeholder with an explicit YAML row list; use [] for empty data."
    ),
    "SCENARIO_OUTSIDE_PROJECT": "Keep the scenario and fixtures inside the project directory.",
    "INIT_OPTIONS_INVALID": "Use --demo alone, or --model with --manifest and optional --catalog.",
    "INIT_METADATA_INVALID": "Use manifest v12 or catalog v1 JSON, at most 64 MiB each.",
    "INIT_ADAPTER_UNSUPPORTED": "Use metadata from a PostgreSQL project.",
    "INIT_PROJECT_MISMATCH": "Use a manifest from the selected dbt project.",
    "INIT_MODEL_AMBIGUOUS": "Select one unversioned model using its full unique_id.",
    "INIT_COLUMNS_MISSING": "Declare columns in model/source YAML or supply a matching --catalog.",
    "INIT_COLUMN_TYPE_MISSING": "Declare each column's data_type or supply a matching --catalog.",
    "INIT_CATALOG_MISMATCH": "Use manifest/catalog files from the same dbt docs invocation.",
    "INIT_PRIMARY_KEY_REQUIRED": "Pass --primary-key for each output key column or set unique_key.",
    "INIT_SCENARIO_NAME_INVALID": "Use a portable name starting with a letter (80 characters max).",
    "INIT_TEMPLATE_UNSUPPORTED": "Selected metadata exceeds the supported scenario schema limits.",
    "MODEL_CONFIGURATION_CHANGED": (
        "Keep routing stable; use only supported materializations, strategies and model settings."
    ),
    "SQL_EXTERNAL_RELATION": (
        "Use declared source/ref fixtures and this; external SQL relations are unsupported."
    ),
    "SQL_AUDIT_UNSUPPORTED": (
        "Use one supported SELECT query without table functions, locks, writes or unknown syntax."
    ),
    "INVALID_CONFIG": (
        "Use a version 1 runner configuration with valid project and database fields."
    ),
    "INVALID_DATABASE_CONFIG": "Check database fields; port must be an integer from 1 to 65535.",
    "INVALID_SCENARIO_SCHEMA": (
        "Check required fields and types against the version 1 scenario schema."
    ),
    "INVALID_YAML": "Use plain YAML without executable tags; check indentation and quoting.",
    "DUPLICATE_YAML_KEY": "Remove the duplicate YAML key.",
    "YAML_ALIAS_UNSUPPORTED": "Expand YAML aliases into explicit values.",
    "YAML_NESTING_LIMIT": "Reduce YAML nesting to at most 128 mapping/sequence levels.",
    "INVALID_TYPED_VALUE": (
        "Match the column type; quote decimals, double precision values and timestamps."
    ),
    "INVALID_COLUMN_NAME": "Quote column names as strings and use at most 63 UTF-8 bytes per name.",
    "FIXTURE_COLUMNS_MISMATCH": "Each row must contain exactly the declared columns.",
    "INVALID_EXPECTED_KEY": "Expected primary keys must be unique and non-null.",
    "INVALID_FIXTURE_PATH": "Use an existing fixture file inside the dbt project.",
    "INVALID_STEP_ORDER": "Use initial for the first step and incremental for every later step.",
    "UNINITIALIZED_INPUT": "Initialize every declared input in the first step.",
    "INVALID_SAME_AS_REFERENCE": "Reference an earlier step from this scenario.",
    "INVALID_RUN_VARS": "Use JSON-compatible vars without NaN, infinity or binary values.",
    "UNSUPPORTED_COLUMN_TYPE": "Use a supported PostgreSQL scalar type, numeric or numeric(p,s).",
    "MISSING_PASSWORD_ENV": "Export the variable named in database.password_env before running.",
    "MISSING_PROJECT_ENV": "Export every variable named in env_allowlist before running.",
    "INVALID_ENV_ALLOWLIST": "Use unique environment names; runner controls cannot be forwarded.",
    "DEPENDENCIES_NOT_INSTALLED": (
        "Run dbt deps in the original project, then retry; the runner does not download packages."
    ),
    "UNSUPPORTED_DEPENDENCY_LOCATION": (
        "Keep installed packages inside the project; external package locations are unsupported."
    ),
    "INVALID_DEPENDENCIES_CONFIG": (
        "Use a supported packages list in packages.yml or dependencies.yml."
    ),
    "INVALID_DBT_PROJECT_CONFIG": "Check dbt_project.yml and its project name.",
    "DBT_PROJECT_NOT_FOUND": "Point project_dir at a directory containing dbt_project.yml.",
    "MODEL_NOT_FOUND": "Set model to an existing model.<project>.<name> unique_id.",
    "INPUT_DEPENDENCIES_MISMATCH": (
        "Add one fixture for each direct source() or ref() dependency."
    ),
    "INIT_WOULD_OVERWRITE": (
        "Choose a new destination or preserve the existing files before initializing."
    ),
    "INIT_UNSAFE_PATH": "Initialize inside a real directory without symlinked destination paths.",
    "DATABASE_ERROR": (
        "Check the dedicated PostgreSQL 16 endpoint, role, password and permissions."
    ),
    "DBT_EXECUTION_ERROR": (
        "Check project dependencies, required vars and env_allowlist; raw dbt errors are withheld."
    ),
    "DBT_ARTIFACT_MISSING": (
        "Retry with a writable temporary directory; dbt did not write required artifacts."
    ),
    "DBT_ARTIFACT_INVALID": (
        "Use the supported dbt Core version and complete, unmodified JSON artifacts."
    ),
    "DBT_ARTIFACT_STALE": (
        "Retry the scenario; artifacts must come from the current dbt invocation."
    ),
    "DBT_ARTIFACT_INVOCATION_MISMATCH": (
        "Retry the scenario; manifest and results must share the current invocation ID."
    ),
    "DBT_ARTIFACT_DIRECTORY_EXISTS": "Use a fresh temporary workspace for every scenario run.",
    "DBT_MODEL_NOT_SUCCESSFUL": (
        "Select one supported model and require its successful execution result."
    ),
    "EXECUTION_MODE_UNVERIFIED": (
        "Use standard materializations without forced full refresh; dbt must emit execution SQL."
    ),
    "NO_SCENARIOS_SELECTED": (
        "Pass --scenario or select a directory containing scenario YAML files."
    ),
    "RUN_STILL_ACTIVE": "Wait for the active runner to finish before cleaning its resources.",
    "STEP_TIMEOUT": "Increase step_timeout or reduce the scenario data and model execution cost.",
    "SCENARIO_TIMEOUT": "Increase scenario_timeout or reduce setup and scenario execution cost.",
}


class ScenarioError(Exception):
    def __init__(self, code: str, *, location=(), line=None, column=None):
        self.code = code
        self.location = tuple(location)
        self.line = line
        self.column = column
        super().__init__(code)

    def diagnostic(self) -> dict:
        result = {"code": self.code, "hint": HINTS.get(self.code)}
        if self.location:
            path = "$"
            for part in self.location:
                if type(part) is int:
                    path += f"[{part}]"
                else:
                    path += f".{part}" if part in FIELDS else "[*]"
            result["location"] = path
        if self.line is not None:
            result["line"] = self.line
            result["column"] = self.column
        return result


def display_error(error: ScenarioError) -> str:
    diagnostic = error.diagnostic()
    text = f"ERROR {error.code}"
    if "location" in diagnostic:
        text += f" at {diagnostic['location']}"
    if "line" in diagnostic:
        text += f" at line {diagnostic['line']}, column {diagnostic['column']}"
    if diagnostic["hint"]:
        text += f"\n  {diagnostic['hint']}"
    return text
