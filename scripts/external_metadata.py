import contextlib
import os
import pathlib
from collections.abc import Iterator
from unittest import mock

from dbt_scenario import config as scenario_config
from dbt_scenario import project as scenario_project


def parse_metadata(
    config: scenario_config.Config,
    directory: pathlib.Path,
    schema: str,
) -> tuple[dict, pathlib.Path]:
    project = scenario_project.Project(config, directory / "parse", schema)
    manifest, artifacts = project.invoke("parse", 120)
    return manifest, artifacts / "target/manifest.json"


@contextlib.contextmanager
def static_metadata(
    password_variable: str = "DSC_TEST_PASSWORD",
) -> Iterator[None]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {password_variable, "DBT_ENV_SECRET_DSC_PASSWORD"}
    }
    with (
        mock.patch.dict(os.environ, environment, clear=True),
        mock.patch(
            "psycopg.connect",
            side_effect=RuntimeError("STATIC_DATABASE_ACCESS"),
        ),
        mock.patch(
            "subprocess.Popen",
            side_effect=RuntimeError("STATIC_SUBPROCESS_ACCESS"),
        ),
    ):
        yield
