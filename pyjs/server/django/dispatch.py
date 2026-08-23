from collections.abc import Awaitable, Callable

from asgiref.sync import async_to_sync

import pyjs.server

_dispatch = async_to_sync(pyjs.server.dispatch)
_dispatch_for_request = async_to_sync(pyjs.server.dispatch_for_request)


def dispatch_sync[**Arguments, Result](
    remote_operation: Callable[Arguments, Awaitable[Result]],
    *args: Arguments.args,
    **kwargs: Arguments.kwargs,
) -> Result:
    return _dispatch(remote_operation, *args, **kwargs)


def dispatch_for_request_sync[**Arguments, Result](
    request: object,
    remote_operation: Callable[Arguments, Awaitable[Result]],
    *args: Arguments.args,
    **kwargs: Arguments.kwargs,
) -> Result:
    return _dispatch_for_request(
        request,
        remote_operation,
        *args,
        **kwargs,
    )
