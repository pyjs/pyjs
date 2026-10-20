"""Experimental JVM bytecode backend."""

import math
import time

from pyjs import jvm
from pyjs.decorators import preserves_numeric_format

from .bindings import (
    JVMBindingError,
    JVMClassBinding,
    JVMExternalClass,
    JVMFieldBinding,
    JVMMethodBinding,
    render_jvm_bindings,
)
from .classpath import (
    JVMAnnotation,
    JVMClass,
    JVMClassFormatError,
    JVMClasspath,
    JVMField,
    JVMMethod,
    JVMParameter,
    JVMTypeAnnotation,
    parse_jvm_method_descriptor,
    read_jvm_class,
)
from .primitives import f32, f64, i32, run_sync
from .reporting import format_exception
from .transpiler import (
    JVMCompilation,
    JVMCompiledTest,
    JVMTest,
    JVMUnsupported,
    transpile_jvm,
)


@jvm.native("java/lang/Object")
class JVMArray[T]:
    """A Java array crossing a direct-JVM native API boundary."""

    __pyjs_jvm_array__ = True
    __pyjs_allow_represented_generics__ = True

    def __init__(self, length: int) -> None:
        pass

    def __len__(self) -> int:
        pass

    @preserves_numeric_format
    def __getitem__(self, index: int) -> T:
        pass

    @preserves_numeric_format
    def __setitem__(self, index: int, value: T) -> None:
        pass


@jvm.native("java/lang/System", name="currentTimeMillis")
def current_time_millis() -> int:
    """Return wall-clock milliseconds on CPython or the JVM."""
    return time.time_ns() // 1_000_000


@jvm.native("java/lang/Double", name="parseDouble")
def parse_double(value: str) -> float:
    """Parse a Java/Python decimal string as a double."""
    return float(value)


@jvm.native("java/lang/Double", name="toString")
def double_to_string(value: float) -> str:
    """Format a finite double for a JVM-facing application."""
    if not math.isfinite(value):
        raise ValueError("non-finite JVM formatting is not portable to Python")
    return str(value)


@jvm.native("java/lang/StringBuilder")
class StringBuilder:
    """A small cross-runtime binding used to prove native JVM objects."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def append(self, value: str) -> StringBuilder:
        self.parts.append(value)
        return self

    @jvm.native(
        "java/lang/StringBuilder",
        name="toString",
        invocation="virtual",
    )
    def to_string(self) -> str:
        return "".join(self.parts)


__all__ = [
    "JVMAnnotation",
    "JVMArray",
    "JVMBindingError",
    "JVMClass",
    "JVMClassBinding",
    "JVMClassFormatError",
    "JVMClasspath",
    "JVMCompilation",
    "JVMCompiledTest",
    "JVMExternalClass",
    "JVMField",
    "JVMFieldBinding",
    "JVMMethod",
    "JVMMethodBinding",
    "JVMParameter",
    "JVMTest",
    "JVMTypeAnnotation",
    "JVMUnsupported",
    "StringBuilder",
    "current_time_millis",
    "double_to_string",
    "f32",
    "f64",
    "format_exception",
    "i32",
    "parse_double",
    "parse_jvm_method_descriptor",
    "read_jvm_class",
    "render_jvm_bindings",
    "run_sync",
    "transpile_jvm",
]
