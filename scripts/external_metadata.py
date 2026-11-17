import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from dbt_scenario.config import Config
from dbt_scenario.project import Project


def parse_metadata(
    config: Config,
    directory: Path,
    schema: str,
) -> tuple[dict, Path]:
    project = Project(config, directory / "parse", schema)
    manifest, artifacts = project.invoke("parse", 120)
    return manifest, artifacts / "target/manifest.json"


@contextmanager
def static_metadata(
    password_variable: str = "DSC_TEST_PASSWORD",
) -> Iterator[None]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {password_variable, "DBT_ENV_SECRET_DSC_PASSWORD"}
    }
    with (
        patch.dict(os.environ, environment, clear=True),
        patch(
            "psycopg.connect",
            side_effect=RuntimeError("STATIC_DATABASE_ACCESS"),
        ),
        patch(
            "subprocess.Popen",
            side_effect=RuntimeError("STATIC_SUBPROCESS_ACCESS"),
        ),
    ):
        yield
