"""Direct WebAssembly emission for the typed native Python subset."""

from .transpiler import (
    WebAssemblyCompilation,
    WebAssemblyUnsupported,
    transpile_webassembly,
)

__all__ = [
    "WebAssemblyCompilation",
    "WebAssemblyUnsupported",
    "transpile_webassembly",
]
