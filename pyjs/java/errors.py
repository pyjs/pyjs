"""Native Java failures, distinct from Python exception classes."""

from pyjs import jvm


@jvm.native("java/lang/ClassCastException")
class ClassCastException(Exception):
    def __init__(self, message: str) -> None: ...


@jvm.native("java/lang/SecurityException")
class SecurityException(Exception):
    def __init__(self, message: str) -> None: ...
