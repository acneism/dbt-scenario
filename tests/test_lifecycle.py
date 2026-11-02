import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

from dbt_scenario.config import Config
from dbt_scenario.deadline import Deadline
from dbt_scenario.errors import ScenarioError
from dbt_scenario.journal import Journal
from dbt_scenario.process import run_process


@pytest.fixture
def config(tmp_path):
    return Config(
        tmp_path,
        {
            "host": "localhost",
            "port": 5432,
            "dbname": "disposable_test",
            "user": "test_role",
            "password": "not-for-the-journal",
        },
    )


def test_journal_is_durable_and_does_not_store_passwords(config):
    run_id = uuid.uuid4().hex
    journal = Journal.create(config, run_id)
    journal.transition("KEPT")
    recovered = Journal.load(config, run_id)
    assert recovered.data["state"] == "KEPT"
    assert recovered.marker() == journal.marker()
    assert config.database["password"] not in recovered.path.read_text()


@pytest.mark.parametrize("run_id", ["../other", "A" * 32, "a" * 31, "", "a" * 33])
def test_cleanup_run_id_cannot_escape_journal_directory(config, run_id):
    with pytest.raises(ScenarioError, match="INVALID_RUN_ID"):
        Journal.load(config, run_id)


def test_journal_cannot_redirect_cleanup_to_another_database(config):
    run_id = uuid.uuid4().hex
    Journal.create(config, run_id)
    config.database["dbname"] = "different_database"
    with pytest.raises(ScenarioError, match="JOURNAL_DATABASE_MISMATCH"):
        Journal.load(config, run_id)


def test_journal_cannot_add_foreign_schemas(config):
    run_id = uuid.uuid4().hex
    journal = Journal.create(config, run_id)
    journal.data["schemas"].append("public")
    journal.save()
    with pytest.raises(ScenarioError, match="INVALID_JOURNAL"):
        Journal.load(config, run_id)


def test_failed_atomic_update_preserves_previous_journal(config, monkeypatch):
    journal = Journal.create(config, uuid.uuid4().hex)
    before = journal.path.read_bytes()

    def fail_replace(*args):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr("dbt_scenario.journal.os.replace", fail_replace)
    with pytest.raises(OSError):
        journal.transition("CLEANED")
    assert journal.path.read_bytes() == before
    assert len(list(journal.path.parent.iterdir())) == 1
    assert json.loads(before)["state"] == "RUNNING"


def test_parent_deadline_cannot_be_extended(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("dbt_scenario.deadline.time.monotonic", lambda: clock[0])
    parent = Deadline(5, "SCENARIO_TIMEOUT")
    child = Deadline(20, "STEP_TIMEOUT", parent)
    assert child.remaining() == 5
    clock[0] = 106
    with pytest.raises(ScenarioError, match="SCENARIO_TIMEOUT"):
        child.check()


def test_subprocess_cannot_outlive_its_budget(tmp_path):
    started = time.monotonic()
    with pytest.raises(ScenarioError, match="STEP_TIMEOUT"):
        run_process(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            dict(os.environ),
            tmp_path,
            Deadline(0.3, "STEP_TIMEOUT"),
        )
    assert time.monotonic() - started < 5


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group semantics")
def test_timeout_kills_a_child_ignoring_sigterm(tmp_path):
    pid_path = tmp_path / "child.pid"
    child = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"Path({str(pid_path)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    parent = (
        f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "time.sleep(60)"
    )
    with pytest.raises(ScenarioError, match="STEP_TIMEOUT"):
        run_process(
            [sys.executable, "-c", parent], dict(os.environ), tmp_path, Deadline(1, "STEP_TIMEOUT")
        )
    pid = int(pid_path.read_text())
    status = Path(f"/proc/{pid}/stat")
    for _ in range(50):
        if not status.exists() or status.read_text().split()[2] == "Z":
            break
        time.sleep(0.02)
    else:
        pytest.fail("child process survived deadline")
