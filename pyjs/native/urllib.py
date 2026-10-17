"""Typed native form-query encoding with CPython as its ordinary fallback."""

import urllib.parse

from pyjs.decorators import ParameterLifetime, native_operation


@native_operation("urllib.parse.urlencode", query=ParameterLifetime.BORROWED)
def urlencode(query: dict[str, str]) -> str:
    return urllib.parse.urlencode(query)
