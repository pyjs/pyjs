"""Callbacks posted to an Android message loop."""

from pyjs import jvm
from pyjs.java.concurrent import Runnable


@jvm.native("android/os/Looper")
class Looper:
    pass


@jvm.native("android/os/Looper", name="getMainLooper")
def main_looper() -> Looper: ...


@jvm.native("android/os/Handler")
class Handler:
    def __init__(self, looper: Looper) -> None: ...

    def post(self, task: Runnable) -> bool: ...

    def postDelayed(self, task: Runnable, delay_ms: int) -> bool: ...
