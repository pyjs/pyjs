"""Native Java tasks and threads; starting a thread does not make work durable."""

from pyjs import jvm


@jvm.native("java/lang/Thread", name="sleep")
def sleep(milliseconds: int) -> None:
    """Pause the calling thread; native interruption and argument errors propagate.

    Use on worker or instrumentation threads, never the Android UI thread.
    """
    ...


@jvm.native("java/lang/Runnable", interface=True)
class Runnable:
    def run(self) -> None: ...


@jvm.native("java/lang/Thread")
class Thread:
    def __init__(self, task: Runnable) -> None: ...

    def start(self) -> None: ...

    def join(self) -> None: ...


@jvm.native("java/util/concurrent/atomic/AtomicBoolean")
class AtomicBoolean:
    def __init__(self, value: bool) -> None: ...

    def get(self) -> bool: ...

    def set(self, value: bool) -> None: ...
