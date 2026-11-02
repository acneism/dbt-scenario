from dbt_scenario.config import Config
from dbt_scenario.database import Database
from dbt_scenario.deadline import Deadline
from dbt_scenario.journal import Journal


def finish_run(database: Database, journal: Journal, keep: bool = False):
    with database.budget(Deadline(10, "CLEANUP_TIMEOUT")):
        database.acquire_run_lock(journal.data["run_id"])
        database.cancel_model_queries(f"dbt-scenario:{journal.data['schemas'][0]}")
        if keep:
            journal.transition("KEPT")
            return "KEPT"
        database.cleanup(journal)
        journal.transition("CLEANED")
        return "CLEANED"


def cleanup_run(config: Config, run_id: str):
    journal = Journal.load(config, run_id)
    if journal.data["state"] == "CLEANED":
        return "CLEANED"
    database = Database(config)
    try:
        return finish_run(database, journal)
    except BaseException:
        if database.locked_run == run_id:
            journal.transition("CLEANUP_FAILED")
        raise
    finally:
        database.close()
