from typing import cast

from pyjs import js
from pyjs.javascript import typeof


@js.native
class _Thenable:
    then: object


@js
def checked_async_result(value: object) -> object:
    """Do not silently assimilate a promise hidden behind an erased type."""
    if value is not None and typeof(cast(_Thenable, value).then) == "function":
        raise TypeError(
            "An async Python return cannot contain a promise or thenable; "
            "await it first or wrap it in a container"
        )
    return value
