from pyjs import js


@js
def cast(value_type: object, value: object) -> object: ...


@cast.analyze
def cast(call):
    return call.static_cast()
