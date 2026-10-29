"""Bounded owned-process execution. Linux/POSIX benchmark host only."""
import os
import signal
import subprocess


def execute(command, *, timeout=30, cwd=None):
    with subprocess.Popen(
        [str(x) for x in command], cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
