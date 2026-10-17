import subprocess

from pyjs.tooling.command import stop_process


class Process:
    def __init__(self, running=True, times_out=False):
        self.running = running
        self.times_out = times_out
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        if timeout is not None and self.times_out:
            raise subprocess.TimeoutExpired("process", timeout)
        self.running = False

    def kill(self):
        self.killed = True


def test_stop_process_terminates_a_running_process():
    process = Process()

    stop_process(process)

    assert process.terminated
    assert not process.killed


def test_stop_process_kills_a_process_that_does_not_exit():
    process = Process(times_out=True)

    stop_process(process)

    assert process.terminated
    assert process.killed


def test_stop_process_leaves_a_finished_process_alone():
    process = Process(running=False)

    stop_process(process)

    assert not process.terminated
