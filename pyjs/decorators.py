import annotationlib
import inspect
from collections.abc import Mapping
from functools import partial
from typing import Annotated, ClassVar, get_origin

DECORATIONS = {
    # safe to analyze and transpile
    "__js__",  # bool

    # include in output even if not visited
    "__js_keep__",  # bool

    # use different implementation of a Python method on client by
    # replacing it with the function in the decoration, which is then
    # transpiled
    "__js_client__",  # function

    # raw JavaScript function body, or a callable returning it
    "__js_source__",  # str | callable
    "__js_source_imports__",  # dict[str, class or function]

    # returns JavaScript source as string, replaces the code at
    # every call site where this function is called
    "__js_inline__",  # function

    # runtime function called in place of the decorated interface
    "__js_inline_call__",  # function

    # runtime function used when an inline function is referenced as a value
    "__js_value__",  # function
    "__js_value_source__",  # str

    # functions referenced by an inline rewrite and retained in generated code
    "__js_inline_dependencies__",  # dict[str, function]

    # returns JavaScript source as string, appending the code
    # after the definition of the wrapped code object
    "__js_append__",  # function receiving reached generated member names
    "__js_member_dependencies__",  # generated member name to required class

    # dispatch a builtin function through a special method on its first argument
    "__js_dispatch__",  # str

    # compiler call analysis attached to the function it describes
    "__js_analysis__",  # callable

    # dunder methods needed by a runtime implementation
    "__js_runtime_dunders__",  # tuple[str | int, tuple[str, ...]]

    # safe to analyze but don't include in output
    "__builtin__",  # bool

    # supplied by the JavaScript target rather than emitted
    "__js_native__",  # bool

    # WebIDL dictionary lowered to a plain JavaScript object
    "__js_dictionary__",  # bool
}


def is_cls_or_func(obj):
    return inspect.isfunction(obj) or inspect.isclass(obj)


def has_inline_decorator(obj):
    obj = getattr(obj, "__func__", obj)
    decorations = getattr(obj, "__dict__", {})
    return bool(
        decorations.get("__js_inline__", False)
        or decorations.get("__js_inline_call__", False)
    )


def has_source_decorator(obj):
    return getattr(obj, "__dict__", {}).get("__js_source__", False)


def should_analyze_func_body(obj):
    function = obj
    obj = getattr(function, "py_obj", function)
    cls = getattr(function, "cls", None)
    if getattr(obj, "__dict__", {}).get("__js_native__", False) or (
        cls is not None
        and getattr(cls.py_obj, "__dict__", {}).get("__js_native__", False)
    ):
        return False
    return not (has_inline_decorator(obj) or has_source_decorator(obj))


def has_keep_decorator(obj):
    return getattr(obj, "__dict__", {}).get("__js_keep__", False)


def should_include(obj):
    runtime_implementation = getattr(obj, "is_runtime_implementation", False)
    kept = has_keep_decorator(obj.py_obj)
    if has_inline_decorator(obj.py_obj) and not kept and not runtime_implementation:
        return False
    is_builtin = getattr(obj.py_obj, "__dict__", {}).get("__builtin__", False)
    if is_builtin and not runtime_implementation:
        return False
    return kept or bool(obj.visited)


class _Implementation:
    def __init__(self, function, attribute: str, name: str):
        self.function = function
        self.attribute = attribute
        self.name = name

    def __call__(self, implementation):
        if not callable(implementation):
            raise TypeError(
                f"@{self.function.__name__}.{self.name} requires a callable."
            )
        setattr(self.function, self.attribute, implementation)
        return self.function


def _compiled_callable(function) -> bool:
    while isinstance(function, partial):
        function = function.func
    return bool(getattr(function, "__js__", False))


class _InlineImplementation(_Implementation):
    def __init__(self, function):
        super().__init__(function, "__js_inline__", "inline")

    def __call__(self, implementation=None, *, dependencies=None):
        if implementation is None:
            if dependencies is None:
                raise TypeError(
                    f"@{self.function.__name__}.inline requires a callable."
                )

            def decorate(implementation):
                return self(implementation, dependencies=dependencies)

            return decorate
        if _compiled_callable(implementation):
            raise TypeError(
                "An inline source generator cannot be marked @js. "
                "Use @js.inline(call=helper) to call a runtime helper."
            )
        if not callable(implementation):
            raise TypeError(
                f"@{self.function.__name__}.inline requires a callable."
            )
        _set_inline(self.function, implementation, dependencies)
        return self.function


class _ValueImplementation(_Implementation):
    def __init__(self, function):
        super().__init__(function, "__js_value__", "value")

    def __call__(self, implementation):
        if not inspect.isfunction(implementation):
            raise TypeError(
                f"@{self.function.__name__}.value requires a function."
            )
        implementation.__js__ = True
        return super().__call__(implementation)

    def source(self, source: str):
        if not isinstance(source, str):
            raise TypeError("A value source implementation must be a string.")
        self.function.__js_value_source__ = source
        return self.function


class _AnalysisImplementation(_Implementation):
    def __init__(self, function):
        super().__init__(function, "__js_analysis__", "analyze")

    def __call__(self, implementation):
        if _compiled_callable(implementation):
            raise TypeError(
                "A call-analysis hook cannot be marked @js because it runs "
                "only in the compiler."
            )
        return super().__call__(implementation)


def _attach_implementation_api(function):
    if "client" not in function.__dict__:
        function.client = _Implementation(function, "__js_client__", "client")
    if "inline" not in function.__dict__:
        function.inline = _InlineImplementation(function)
    if "value" not in function.__dict__:
        function.value = _ValueImplementation(function)
    if "analyze" not in function.__dict__:
        function.analyze = _AnalysisImplementation(function)

    def source(source):
        if not isinstance(source, str) and not callable(source):
            raise TypeError(
                "A JavaScript source implementation must be a string or callable."
            )
        function.__js_source__ = source
        return function

    function.source = source


def _class_instance_annotations(cls: type) -> dict[str, object]:
    annotations = annotationlib.get_annotations(
        cls,
        format=annotationlib.Format.FORWARDREF,
    )
    annotate = cls.__annotate__
    globals_ = annotate.__globals__ if annotate is not None else {}
    for name, annotation in annotations.items():
        if isinstance(annotation, annotationlib.ForwardRef):
            annotations[name] = annotation.evaluate(
                globals=globals_,
                locals={cls.__name__: cls},
                owner=None,
            )
    return {
        name: annotation
        for name, annotation in annotations.items()
        if name not in vars(cls) and get_origin(annotation) is not ClassVar
    }


def js(obj):
    obj.__js__ = True
    if inspect.isclass(obj):
        if "__pyjs_instance_annotations__" not in vars(obj):
            obj.__pyjs_instance_annotations__ = _class_instance_annotations(obj)
    else:
        _attach_implementation_api(obj)
    return obj


def _set_inline(function, source, dependencies=None):
    if isinstance(source, str):
        template = source.replace("{*args}", "{_args_suffix}")
        function.__js_inline__ = lambda **kwargs: template.format(**kwargs)
    elif callable(source):
        if _compiled_callable(source):
            raise TypeError(
                "An @js.inline source generator cannot be marked @js. "
                "Use @js.inline(call=helper) to call a runtime helper."
            )
        function.__js_inline__ = source
    else:
        raise TypeError("@js.inline requires a source string or callable.")

    if dependencies is None:
        return
    target = function.__qualname__
    if not isinstance(dependencies, Mapping):
        raise TypeError(f"@js.inline dependencies for {target!r} must be a mapping.")
    invalid_names = [
        name
        for name in dependencies
        if not isinstance(name, str) or not name.isidentifier()
    ]
    if invalid_names:
        names = ", ".join(repr(name) for name in invalid_names)
        raise TypeError(
            f"@js.inline dependency names for {target!r} must be Python "
            f"identifiers; invalid: {names}."
        )
    invalid_dependencies = [
        (name, type(dependency).__name__)
        for name, dependency in dependencies.items()
        if not inspect.isfunction(dependency)
    ]
    if invalid_dependencies:
        values = ", ".join(
            f"{name!r} ({type_name})"
            for name, type_name in invalid_dependencies
        )
        raise TypeError(
            f"@js.inline dependencies for {target!r} must be functions; "
            f"invalid: {values}."
        )
    reserved = {
        "_arg_strs",
        "_arg_types",
        "_keyword_strs",
        "_args_joined",
        "_args_suffix",
        "self",
    }
    parameter_names = set(inspect.signature(function).parameters)
    conflicts = set(dependencies) & (reserved | parameter_names)
    if conflicts:
        raise TypeError(
            f"@js.inline dependency names for {target!r} conflict with call "
            f"arguments: {', '.join(sorted(conflicts))}."
        )
    function.__js_inline_dependencies__ = dict(dependencies)


def _js_inline(source=None, *, call=None, dependencies=None):
    if (source is None) == (call is None):
        raise TypeError("@js.inline requires exactly one of source or call.")
    if call is not None:
        if dependencies is not None:
            raise TypeError(
                "@js.inline(call=...) does not accept separate dependencies."
            )
        if not inspect.isfunction(call):
            raise TypeError("@js.inline call target must be a function marked @js.")
        if not getattr(call, "__js__", False):
            raise TypeError("@js.inline call target must be marked @js.")
        if has_inline_decorator(call):
            raise TypeError("@js.inline call target must emit a runtime function.")

    def decorate(obj):
        obj = js(obj)
        if call is not None:
            obj.__js_inline_call__ = call
        else:
            _set_inline(obj, source, dependencies)
        return obj

    return decorate


def _js_native(obj):
    if is_cls_or_func(obj):
        obj = js(obj)
    else:
        obj.__js__ = True
        obj.__static__ = True
    obj.__builtin__ = True
    obj.__js_native__ = True
    return obj


def _js_dictionary(cls):
    if not inspect.isclass(cls):
        raise TypeError("@js.dictionary is only supported for classes.")
    cls = js(cls)
    cls.__js_dictionary__ = True
    return cls


def _js_keep(obj):
    if inspect.isclass(obj) or "." not in obj.__qualname__:
        raise TypeError("@js.keep is only supported for class methods.")
    obj = js(obj)
    obj.__js_keep__ = True
    return obj


def _js_dispatch(method_name: str):
    if not (
        isinstance(method_name, str)
        and method_name.startswith("__")
        and method_name.endswith("__")
    ):
        raise TypeError("@js.dispatch requires a dunder method name.")

    def decorate(obj):
        obj = js(obj)
        obj.__js_dispatch__ = method_name
        return obj

    return decorate


def _js_runtime_dunders(*method_names: str, item_of: int | str):
    if item_of != "self" and not (
        isinstance(item_of, int) and not isinstance(item_of, bool) and item_of >= 0
    ):
        raise TypeError(
            "@js.runtime_dunders item_of must be 'self' or an argument index."
        )
    if not method_names or any(
        not isinstance(name, str)
        or not name.startswith("__")
        or not name.endswith("__")
        for name in method_names
    ):
        raise TypeError(
            "@js.runtime_dunders requires one or more dunder method names."
        )

    def decorate(obj):
        obj = js(obj)
        obj.__js_runtime_dunders__ = (item_of, method_names)
        return obj

    return decorate


def nojs(cls_func):
    cls_func.__js__ = False
    return cls_func


js.inline = _js_inline
js.native = _js_native
js.dictionary = _js_dictionary
js.keep = _js_keep
js.dispatch = _js_dispatch
js.runtime_dunders = _js_runtime_dunders


type JS[T] = Annotated[T, js]
