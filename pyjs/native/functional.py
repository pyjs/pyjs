"""Typed native declarations for standard functional operations."""

import functools
from collections.abc import Callable, Iterable
from typing import overload

from pyjs.decorators import ParameterLifetime, configure_js, native_operation


class Placeholder:
    """Analysis-only marker; native partials encode holes in their signature."""


@native_operation("functools.partial", function=ParameterLifetime.RETURNED,
                  args=ParameterLifetime.RETURNED, keywords=ParameterLifetime.RETURNED)
def partial(function: object, /, *args: object, **keywords: object) -> object:
    return functools.partial(function, *args, **keywords)


def _analyze_partial(call):
    from .partials import analyze
    return analyze(call)


configure_js(partial, analysis=_analyze_partial)


@overload
def reduce[T](function: Callable[[T, T], T], iterable: Iterable[T], /) -> T: ...


@overload
def reduce[T, V](function: Callable[[T, V], T], iterable: Iterable[V], /,
                  initial: T) -> T: ...


@native_operation("functools.reduce")
def reduce(function: object, iterable: object, /, *initial: object,
           **options: object) -> object:
    return functools.reduce(function, iterable, *initial, **options)
