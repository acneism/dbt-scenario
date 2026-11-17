import datetime
import hashlib
import json
import os
import pathlib
import re
import secrets
import tempfile

from dbt_scenario import config as scenario_config
from dbt_scenario import errors

RUN_ID = re.compile(r"^[a-f0-9]{32}$")
STATES = {"RUNNING", "KEPT", "CLEANUP_FAILED", "CLEANED"}


def database_fingerprint(config: scenario_config.Config) -> str:
    identity = {
        key: config.database[key] for key in ["host", "port", "dbname", "user"]
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()
    ).hexdigest()


def schema_names(run_id: str) -> list[str]:
    if not RUN_ID.fullmatch(run_id):
        raise errors.ScenarioError("INVALID_RUN_ID")
    return [f"dsc_{run_id}_{suffix}" for suffix in ["a", "i", "e"]]


def journal_path(config: scenario_config.Config, run_id: str) -> pathlib.Path:
    schema_names(run_id)
    directory = config.project_dir / ".dbt-scenario" / "runs"
    if any(
        path.is_symlink()
        for path in [directory.parent, directory, directory / f"{run_id}.json"]
    ):
        raise errors.ScenarioError("JOURNAL_SYMLINK_UNSUPPORTED")
    return directory / f"{run_id}.json"


class Journal:
    def __init__(self, path: pathlib.Path, data: dict) -> None:
        self.path = path
        self.data = data

    @classmethod
    def create(cls, config: scenario_config.Config, run_id: str) -> "Journal":
        path = journal_path(config, run_id)
        if path.exists():
            raise errors.ScenarioError("JOURNAL_ALREADY_EXISTS")
        journal = cls(
            path,
            {
                "schema_version": 1,
                "run_id": run_id,
                "database_fingerprint": database_fingerprint(config),
                "owner": config.database["user"],
                "ownership_token": secrets.token_hex(32),
                "schemas": schema_names(run_id),
                "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "state": "RUNNING",
            },
        )
        journal.save()
        return journal

    @classmethod
    def load(cls, config: scenario_config.Config, run_id: str) -> "Journal":
        path = journal_path(config, run_id)
        if not path.is_file():
            raise errors.ScenarioError("JOURNAL_NOT_FOUND")
        if path.stat().st_size > 16384:
            raise errors.ScenarioError("INVALID_JOURNAL")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise errors.ScenarioError("INVALID_JOURNAL") from None
        required = {
            "schema_version",
            "run_id",
            "database_fingerprint",
            "owner",
            "ownership_token",
            "schemas",
            "created_at",
            "state",
        }
        if (
            not isinstance(data, dict)
            or set(data) != required
            or data["schema_version"] != 1
            or data["run_id"] != run_id
            or data["schemas"] != schema_names(run_id)
            or not isinstance(data["ownership_token"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", data["ownership_token"])
            or not isinstance(data["state"], str)
            or data["state"] not in STATES
        ):
            raise errors.ScenarioError("INVALID_JOURNAL")
        if (
            data["database_fingerprint"] != database_fingerprint(config)
            or data["owner"] != config.database["user"]
        ):
            raise errors.ScenarioError("JOURNAL_DATABASE_MISMATCH")
        return cls(path, data)

    def marker(self) -> str:
        return json.dumps(
            {
                "tool": "dbt-scenario",
                "run_id": self.data["run_id"],
                "ownership_token": self.data["ownership_token"],
            },
            sort_keys=True,
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, name = tempfile.mkstemp(
            prefix=".journal-", dir=self.path.parent
        )
        temporary = pathlib.Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(self.data, output, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def transition(self, state: str) -> None:
        if state not in STATES:
            raise errors.ScenarioError("INVALID_JOURNAL_STATE")
        self.data["state"] = state
        self.save()
