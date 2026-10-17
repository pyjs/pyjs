"""Interface imports for backends sharing the native Python builtin model."""

import builtins
import collections.abc
import typing

from pyjs.analysis.libraries import LibraryMappings


class NativeProtocolMappings(LibraryMappings):
    def resolve(self, value):
        from . import native

        if value is builtins.pow:
            return native._pow
        if value is builtins.reversed:
            return native._reversed
        if value is builtins.sorted:
            return native._sorted
        if value is builtins.getattr:
            return native._getattr
        if value is builtins.hasattr:
            return native._hasattr
        if value is type(NotImplemented):
            return native._NotImplementedType
        # Resolve the value, not its containing module: redirecting imports
        # back into native.py while that builtin module loads recurses.
        for name in ("KeysView", "ValuesView", "ItemsView", "Iterator", "Iterable", "Generator", "Awaitable"):
            if value is getattr(collections.abc, name) or value is getattr(typing, name):
                return getattr(native, "_" + name)
        return super().resolve(value)
