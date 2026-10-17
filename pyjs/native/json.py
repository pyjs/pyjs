"""Typed native JSON output, with the standard Python implementation as oracle."""

import json

from pyjs.decorators import ParameterLifetime, native_operation


@native_operation("json.dumps", obj=ParameterLifetime.BORROWED)
def dumps[T](obj: T, *, skipkeys: bool = False, ensure_ascii: bool = True,
             check_circular: bool = True, allow_nan: bool = True,
             cls: object | None = None, indent: int | str | None = None,
             separators: tuple[str, str] | None = None, default: object | None = None,
             sort_keys: bool = False) -> str:
    return json.dumps(obj, skipkeys=skipkeys, ensure_ascii=ensure_ascii,
                      check_circular=check_circular, allow_nan=allow_nan,
                      cls=cls, indent=indent, separators=separators,
                      default=default, sort_keys=sort_keys)
