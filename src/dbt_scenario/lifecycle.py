from typing import Literal

from dbt_scenario import config as scenario_config
from dbt_scenario import database as scenario_database
from dbt_scenario import deadline
from dbt_scenario import journal as scenario_journal


def finish_run(
    database: scenario_database.Database,
    journal: scenario_journal.Journal,
    keep: bool = False,
) -> Literal["KEPT", "CLEANED"]:
    with database.budget(deadline.Deadline(10, "CLEANUP_TIMEOUT")):
        database.acquire_run_lock(journal.data["run_id"])
        database.cancel_model_queries(
            f"dbt-scenario:{journal.data['schemas'][0]}"
        )
        if keep:
            journal.transition("KEPT")
            return "KEPT"
        database.cleanup(journal)
        journal.transition("CLEANED")
        return "CLEANED"


def cleanup_run(
    config: scenario_config.Config, run_id: str
) -> Literal["CLEANED"]:
    journal = scenario_journal.Journal.load(config, run_id)
    if journal.data["state"] == "CLEANED":
        return "CLEANED"
    database = scenario_database.Database(config)
    try:
        return finish_run(database, journal)
    except BaseException:
        if database.locked_run == run_id:
            journal.transition("CLEANUP_FAILED")
        raise
    finally:
        database.close()
