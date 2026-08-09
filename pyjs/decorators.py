import inspect
from collections.abc import Mapping
from typing import Annotated

DECORATIONS = {
    # safe to analyze and transpile
    "__js__",  # bool

    # do not analyze or transpile
    # eg. class is marked safe but you want to exclude a specific method
    "__nojs__",  # bool

    # include in output even if not visited
    "__js_include__",  # bool

    # use different implementation of a Python method on client by
    # replacing it with the function in the decoration, which is then
    # transpiled
    "__js_replace__",  # function

    # similar to __js_replace__ but no transpiling occurs; instead,
    # the function is expected to return the JavaScript source as string
    "__js_rewrite_func__",  # function

    # returns JavaScript source as string, replaces the code at
    # every call site where this function is called
    "__js_rewrite_call_site__",  # function

    # functions referenced by an inline rewrite and retained in generated code
    "__js_inline_dependencies__",  # dict[str, function]

    # returns JavaScript source as string, appending the code
    # after the definition of the wrapped code object
    "__js_append__",  # function

    # dispatch a builtin function through a special method on its first argument
    "__js_dunder_dispatch__",  # str

    # safe to analyze but don't include in output
    "__builtin__",  # bool

    # do not analyze function
    "__no_analyze__",  # bool
}


def dunder_dispatch(method_name: str):
    def decorate(func):
        func.__js_dunder_dispatch__ = method_name
        return func

    return decorate


def is_cls_or_func(obj):
    return inspect.isfunction(obj) or inspect.isclass(obj)


def has_inline_decorator(obj):
    return getattr(obj, "__dict__", {}).get("__js_rewrite_call_site__", False)


def has_source_decorator(obj):
    return getattr(obj, "__dict__", {}).get("__js_rewrite_func__", False)


def has_no_analyze(obj):
    return getattr(obj, "__dict__", {}).get("__no_analyze__", False)


def should_analyze_func_body(obj):
    return not (
        has_inline_decorator(obj) or
        has_source_decorator(obj) or
        has_no_analyze(obj)
    )


def has_include_decorator(obj):
    return getattr(obj, "__dict__", {}).get("__js_include__", False)


def should_include(obj):
    if has_inline_decorator(obj.py_obj) and not has_include_decorator(obj.py_obj):
        return False
    return (
        has_include_decorator(obj.py_obj) or
        bool(obj.visited)
    ) and not getattr(obj.py_obj, "__dict__", {}).get("__builtin__", False)


def js(
    *cls_func_args,
    inline=None,
    dependencies=None,
    builtin=None,
    include=None,
    analyze=None,
    client=None,
):

    class Wrapper:

        def __init__(self, inline, dependencies, builtin, include, analyze, client):
            self.inline = inline
            self.dependencies = dependencies
            self.builtin = builtin
            self.include = include
            self.analyze = analyze
            self.client_implementation = client

        def __call__(self, cls_func):
            cls_func.__js__ = True

            if self.builtin is True:
                cls_func.__builtin__ = True

            if self.inline is not None:
                if isinstance(self.inline, str):
                    inline_template = self.inline.replace("{*args}", "{_args_suffix}")
                    cls_func.__js_rewrite_call_site__ = (
                        lambda **kwargs: inline_template.format(**kwargs)
                    )
                else:
                    cls_func.__js_rewrite_call_site__ = self.inline

            if self.dependencies is not None:
                target = cls_func.__qualname__
                if self.inline is None:
                    raise TypeError(
                        f"@js dependencies for {target!r} require an inline= argument."
                    )
                if not isinstance(self.dependencies, Mapping):
                    raise TypeError(
                        f"@js dependencies for {target!r} must be a mapping."
                    )
                invalid_names = [
                    name
                    for name in self.dependencies
                    if not isinstance(name, str) or not name.isidentifier()
                ]
                if invalid_names:
                    names = ", ".join(repr(name) for name in invalid_names)
                    raise TypeError(
                        f"@js dependency names for {target!r} must be Python "
                        f"identifiers; invalid: {names}."
                    )
                invalid_dependencies = [
                    (name, type(dependency).__name__)
                    for name, dependency in self.dependencies.items()
                    if not inspect.isfunction(dependency)
                ]
                if invalid_dependencies:
                    dependencies = ", ".join(
                        f"{name!r} ({type_name})"
                        for name, type_name in invalid_dependencies
                    )
                    raise TypeError(
                        f"@js dependencies for {target!r} must be functions; "
                        f"invalid: {dependencies}."
                    )
                reserved = {
                    "_arg_strs",
                    "_arg_types",
                    "_keyword_strs",
                    "_args_joined",
                    "_args_suffix",
                    "self",
                }
                parameter_names = set(inspect.signature(cls_func).parameters)
                conflicts = set(self.dependencies) & (reserved | parameter_names)
                if conflicts:
                    raise TypeError(
                        f"@js dependency names for {target!r} conflict with call "
                        f"arguments: {', '.join(sorted(conflicts))}."
                    )
                cls_func.__js_inline_dependencies__ = dict(self.dependencies)

            if inspect.isclass(cls_func):
                if self.include is not None:
                    raise TypeError(
                        "@js(include=True) is only supported for class methods."
                    )
                if self.client_implementation is not None:
                    raise TypeError("@js(client=...) is not supported for classes.")
                return cls_func

            if self.client_implementation is not None:
                if self.inline is not None:
                    raise TypeError(
                        "@js(client=...) cannot be combined with inline=."
                    )
                cls_func.__js_replace__ = self.client_implementation

            if self.include is True:
                if "." not in cls_func.__qualname__:
                    raise TypeError(
                        "@js(include=True) is only supported for class methods."
                    )
                cls_func.__js_include__ = True

            if self.analyze is False:
                cls_func.__no_analyze__ = True

            def client(new_func: type):
                cls_func.__js_replace__ = new_func
                return cls_func
            cls_func.client = client

            def source(new_func: type):
                cls_func.__js_rewrite_func__ = new_func
                return cls_func
            cls_func.source = source

            def inline(new_func: type):
                cls_func.__js_rewrite_call_site__ = new_func
                return cls_func
            cls_func.inline = inline

            return cls_func

    if cls_func_args and is_cls_or_func(cls_func_args[0]):
        return Wrapper(
            inline, dependencies, builtin, include, analyze, client
        )(cls_func_args[0])

    return Wrapper(inline, dependencies, builtin, include, analyze, client)


def nojs(cls_func):
    cls_func.__js__ = False
    return cls_func


def js_object(obj, builtin=None, include=None):
    obj.__js__ = True
    obj.__static__ = True
    if builtin is True:
        obj.__builtin__ = builtin
    if include is True:
        obj.__js_include__ = True
    return obj


type JS[T] = Annotated[T, js]
