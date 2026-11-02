import os
import signal
import subprocess

from dbt_scenario.deadline import Deadline
from dbt_scenario.errors import ScenarioError


def stop_process(process: subprocess.Popen):
    if os.name == "nt" and process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
    finally:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def run_process(argv: list[str], environment: dict, directory, deadline: Deadline) -> int:
    deadline.check()
    process = subprocess.Popen(
        argv,
        env=environment,
        cwd=directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        process.communicate(timeout=deadline.remaining())
    except subprocess.TimeoutExpired:
        stop_process(process)
        raise ScenarioError(deadline.expired_reason()) from None
    except BaseException:
        stop_process(process)
        raise
    deadline.check()
    return process.returncode
