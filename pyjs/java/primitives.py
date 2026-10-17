"""JVM primitive types and native reference metadata."""

import asyncio
from dataclasses import dataclass
from typing import Awaitable  # noqa: UP035 - PyJS resolves typing aliases directly.

from pyjs import jvm
from pyjs.decorators import JVM_INTERNAL_NAME
from pyjs.numeric import NumericFormat, _FixedFloat, _FixedInteger


class i32(_FixedInteger):
    """JVM ``int`` semantics for native JVM signatures."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat(
        "integer",
        32,
        True,
        domain="java",
    )


class f32(_FixedFloat):
    """JVM ``float`` semantics for native JVM signatures."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("float", 32, domain="java")


class f64(_FixedFloat):
    """JVM ``double`` semantics for native JVM signatures."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("float", 64, domain="java")


@dataclass(frozen=True)
class Reference:
    owner: str

    def __post_init__(self) -> None:
        if JVM_INTERNAL_NAME.fullmatch(self.owner) is None:
            raise TypeError("JVM reference owner must be a valid internal name")


@jvm.native("pyjs/runtime/Async", name="runSync")
def run_sync[T](awaitable: Awaitable[T]) -> T:
    """Run one immediate JVM async chain from synchronous application code."""
    return asyncio.run(awaitable)


__all__ = ["f32", "f64", "i32", "run_sync"]
