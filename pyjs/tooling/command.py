import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


def stop_process(process: subprocess.Popen, timeout: float = 5) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


class CommandRunner:
    def __init__(self, environment: Mapping[str, str] | None = None):
        self.environment = dict(environment or {})

    def env(self, environment: Mapping[str, str] | None = None) -> dict[str, str]:
        result = os.environ.copy()
        result.update(self.environment)
        result.update(environment or {})
        return result

    def run(
        self,
        command: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        capture_output: bool = False,
        input: str | bytes | None = None,
        check: bool = True,
        pass_fds: tuple[int, ...] = (),
        text: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [str(part) for part in command],
            cwd=cwd,
            env=self.env(environment),
            check=check,
            capture_output=capture_output,
            input=input,
            pass_fds=pass_fds,
            text=text,
            timeout=timeout,
        )

    def start(
        self,
        command: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        detached: bool = False,
    ) -> subprocess.Popen:
        options = {}
        if detached:
            options.update(
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if os.name == "nt":
                options["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                options["start_new_session"] = True
        return subprocess.Popen(
            [str(part) for part in command],
            cwd=cwd,
            env=self.env(environment),
            **options,
        )
