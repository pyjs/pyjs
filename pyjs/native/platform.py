"""Host C-runtime boundaries for native compilation (not cross-compilation)."""

import ctypes
import sys
from functools import cache


@cache
def libc():
    # Windows does not expose the CRT through the process executable handle.
    # Use the same universal CRT as the compiled programs and CPython's files.
    return ctypes.CDLL("ucrtbase.dll" if sys.platform == "win32" else None, use_errno=True)


def errno_symbol():
    return {"darwin": "__error", "win32": "_errno"}.get(sys.platform, "__errno_location")


def binary_suffix(*, shared=False):
    if sys.platform == "win32":
        return ".dll" if shared else ".exe"
    return (".dylib" if sys.platform == "darwin" else ".so") if shared else ""
