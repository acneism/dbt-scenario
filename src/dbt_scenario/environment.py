import os
import re

from dbt_scenario.errors import ScenarioError

BASE_NAMES = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
RESERVED_NAMES = BASE_NAMES | {
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "COMSPEC",
    "PATHEXT",
    "SHELL",
    "ENV",
    "BASH_ENV",
    "IFS",
    "CDPATH",
    "DBT_ENV_SECRET_DSC_PASSWORD",
    "OPENSSL_CONF",
    "OPENSSL_MODULES",
    "SSLKEYLOGFILE",
}
RESERVED_PREFIXES = ("PG", "PYTHON", "LD_", "DYLD_", "GIT_", "PIP_", "UV_")


def validate_names(names):
    if not isinstance(names, list) or len(names) > 64:
        raise ScenarioError("INVALID_ENV_ALLOWLIST", location=("env_allowlist",))
    seen = set()
    for index, name in enumerate(names):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
            raise ScenarioError("INVALID_ENV_ALLOWLIST", location=("env_allowlist", index))
        normalized = name.upper()
        if (
            normalized in seen
            or normalized in RESERVED_NAMES
            or normalized.startswith(RESERVED_PREFIXES)
            or (normalized.startswith("DBT_") and not normalized.startswith("DBT_ENV_SECRET_"))
        ):
            raise ScenarioError("INVALID_ENV_ALLOWLIST", location=("env_allowlist", index))
        seen.add(normalized)


def selected_environment(names, password_name: str) -> dict[str, str]:
    validate_names(names)
    selected = {}
    for index, name in enumerate(names):
        if name.upper() == password_name.upper():
            raise ScenarioError("INVALID_ENV_ALLOWLIST", location=("env_allowlist", index))
        if name not in os.environ:
            raise ScenarioError("MISSING_PROJECT_ENV", location=("env_allowlist", index))
        selected[name] = os.environ[name]
    return selected


def process_environment(project_env: dict[str, str], password: str) -> dict[str, str]:
    validate_names(list(project_env))
    environment = {key: value for key, value in os.environ.items() if key.upper() in BASE_NAMES}
    environment.update(project_env)
    environment.update(
        {
            "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
            "DBT_PARTIAL_PARSE": "false",
            "DBT_ENV_SECRET_DSC_PASSWORD": password,
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return environment
