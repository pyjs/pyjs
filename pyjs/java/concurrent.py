"""Native Java tasks and threads; starting a thread does not make work durable."""

from pyjs import jvm


@jvm.native("java/lang/Runnable", interface=True)
class Runnable:
    def run(self) -> None: ...


@jvm.native("java/lang/Thread")
class Thread:
    def __init__(self, task: Runnable) -> None: ...

    def start(self) -> None: ...

    def join(self) -> None: ...
