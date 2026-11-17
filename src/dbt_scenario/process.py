import os
import signal
import subprocess
import sys

from dbt_scenario.deadline import Deadline
from dbt_scenario.errors import ScenarioError
from dbt_scenario.windows_job import WindowsJob

WINDOWS_LAUNCHER = (
    "import subprocess\n"
    "import sys\n"
    "\n"
    "if sys.stdin.buffer.read(1) != b'1':\n"
    "    sys.exit(125)\n"
    "sys.exit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL))\n"
)


def stop_process(process: subprocess.Popen):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_process(
    argv: list[str], environment: dict, directory, deadline: Deadline
) -> int:
    deadline.check()
    job = WindowsJob() if os.name == "nt" else None
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", WINDOWS_LAUNCHER, *argv]
            if job
            else argv,
            env=environment,
            cwd=directory,
            stdin=subprocess.PIPE if job else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NO_WINDOW if job else 0,
        )
        if job:
            job.assign(process.pid)
        process.communicate(
            input=b"1" if job else None, timeout=deadline.remaining()
        )
    except subprocess.TimeoutExpired:
        raise ScenarioError(deadline.expired_reason()) from None
    finally:
        if job:
            job.close()
            if process:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        elif process:
            stop_process(process)
        if process:
            for stream in [process.stdin, process.stdout, process.stderr]:
                if stream:
                    stream.close()
    deadline.check()
    return process.returncode
