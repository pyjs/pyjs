"""Direct WebAssembly emission for the typed native Python subset."""

from .memory import (
    grow_memory,
    load_f32,
    load_f64,
    load_i32,
    memory_byte_length,
    memory_bytes,
    reset_memory,
    store_f32,
    store_f64,
    store_i32,
)
from .transpiler import (
    WebAssemblyCompilation,
    WebAssemblyUnsupported,
    transpile_webassembly,
)

__all__ = [
    "WebAssemblyCompilation",
    "WebAssemblyUnsupported",
    "transpile_webassembly",
    "grow_memory",
    "load_f32",
    "load_f64",
    "load_i32",
    "memory_byte_length",
    "memory_bytes",
    "reset_memory",
    "store_f32",
    "store_f64",
    "store_i32",
]
