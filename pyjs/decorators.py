import annotationlib
import inspect
import re
import string
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import partial, wraps
from types import MappingProxyType
from typing import Annotated, ClassVar, Literal, TypeAliasType, get_args, get_origin

DECORATIONS = {
    # Target-neutral metadata consumed by shared analysis.
    "__pyjs_analysis__",

    # One record per backend keeps output-specific metadata together.
    "__js__",  # JSDecoration
    "__wgsl__",
    "__native__",
    "__jvm__",

    # safe to analyze but don't include in output
    "__builtin__",  # bool
}

JVM_INTERNAL_NAME = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:/[A-Za-z_$][A-Za-z0-9_$]*)*"
)


class ParameterLifetime(StrEnum):
    """How a backend declaration may retain one call argument."""

    BORROWED = "borrowed"
    RETURNED = "returned"
    EXTERNAL = "external"


@dataclass(frozen=True)
class AnalysisDecoration:
    """Target-neutral facts supplied by declarations and external runtimes."""

    parameter_lifetimes: Mapping[str, ParameterLifetime] | None = None
    preserves_numeric_format: bool = False
    integer_index_parameters: tuple[str, ...] | None = None


_EMPTY_PARAMETER_LIFETIMES = MappingProxyType({})


@dataclass(frozen=True)
class JSImplementation:
    kind: Literal["inline", "call", "native", "source", "function"]
    value: object = None


@dataclass(frozen=True)
class JSDecoration:
    """All JavaScript-specific metadata attached to one Python object."""

    enabled: bool | None = None
    implementation: JSImplementation | None = None
    client: object = None
    value: JSImplementation | None = None
    keep: bool | None = None
    references: Mapping[str, object] | None = None
    post_definition_source: object = None
    member_dependencies: dict[str, object] | None = None
    bind_source: object = None
    dispatch: str | None = None
    analysis: object = None
    runtime_dunders: tuple[int | str, tuple[str, ...]] | None = None
    dictionary: bool | None = None
    runtime_type: type | None = None

    @property
    def kind(self) -> str:
        return self.implementation.kind if self.implementation is not None else "emit"

    @property
    def declaration(self) -> bool:
        return self.kind != "emit"


@dataclass(frozen=True)
class WGSLDecoration:
    kind: Literal["emit", "native", "inline"]
    template: str | None = None

    @property
    def declaration(self) -> bool:
        return self.kind != "emit"


@dataclass(frozen=True)
class NativeDecoration:
    """One operation supplied by the native backend runtime."""

    operation: str | None = None
    constant: str | None = None
    kind: Literal["native", "inline", "runtime"] = "native"
    template: str | None = None

    @property
    def declaration(self) -> bool:
        return self.kind != "runtime"


@dataclass(frozen=True)
class JVMDecoration:
    kind: Literal["native"]
    owner: str
    name: str | None = None
    invocation: Literal["static", "virtual"] = "static"
    interface: bool = False

    @property
    def declaration(self) -> bool:
        return True


@dataclass(frozen=True)
class JVMField:
    name: str | None = None
    writable: bool = True


def _configure_analysis(obj, **values):
    target = getattr(obj, "__func__", obj)
    current = getattr(target, "__dict__", {}).get("__pyjs_analysis__")
    if current is not None and not isinstance(current, AnalysisDecoration):
        raise TypeError(
            f"{target.__qualname__!r} has invalid shared analysis metadata."
        )
    target.__pyjs_analysis__ = replace(
        current or AnalysisDecoration(),
        **values,
    )
    return obj


def own_js_decoration(obj) -> JSDecoration | None:
    obj = getattr(obj, "__func__", obj)
    decoration = getattr(obj, "__dict__", {}).get("__js__")
    return decoration if isinstance(decoration, JSDecoration) else None


def configure_js(obj, **values):
    target = getattr(obj, "__func__", obj)
    decoration = own_js_decoration(target) or JSDecoration()
    target.__js__ = replace(decoration, **values)
    return obj


def js_metadata(obj, name: str, default=None):
    """Read JS metadata with normal class and instance inheritance."""
    obj = getattr(obj, "__func__", obj)
    if inspect.isclass(obj):
        owners = obj.__mro__
    elif inspect.isfunction(obj):
        owners = (obj,)
    else:
        owners = (obj, *type(obj).__mro__)
    for owner in owners:
        decoration = getattr(owner, "__dict__", {}).get("__js__")
        if isinstance(decoration, JSDecoration):
            value = getattr(decoration, name, None)
            if value is not None:
                return value
    return default


def backend_metadata(obj, backend: str, name: str, default=None):
    """Read one field from a backend record with normal inheritance."""
    if backend == "js":
        return js_metadata(obj, name, default)
    obj = getattr(obj, "__func__", obj)
    if inspect.isclass(obj):
        owners = obj.__mro__
    elif inspect.isfunction(obj):
        owners = (obj,)
    else:
        owners = (obj, *type(obj).__mro__)
    for owner in owners:
        decoration = getattr(owner, "__dict__", {}).get(f"__{backend}__")
        value = getattr(decoration, name, None)
        if value is not None:
            return value
    return default


def backend_references(obj, backend: str) -> Mapping[str, object]:
    return backend_metadata(obj, backend, "references", {})


def _parameter_names(target):
    """Inspect declaration names without requiring forward annotation names."""
    try:
        signature = inspect.signature(target, annotation_format=annotationlib.Format.STRING)
    except Exception:
        # CPython's stringifier cannot represent every valid expression (for
        # example, formatted Annotated metadata or an unpacking comprehension).
        # Fake globals can also make valid lookups fail, so there is no fixed
        # exception set. Retry real values with late names still allowed;
        # genuine signature/annotation errors propagate from that attempt.
        signature = inspect.signature(target, annotation_format=annotationlib.Format.FORWARDREF)
    return signature.parameters.keys()


def configure_parameter_lifetimes(
    obj,
    lifetimes: Mapping[str, ParameterLifetime],
):
    """Attach one backend-independent parameter retention contract."""
    target = getattr(obj, "__func__", obj)
    current = getattr(target, "__dict__", {}).get("__pyjs_analysis__")
    values = dict(lifetimes)
    invalid_values = [
        name
        for name, lifetime in values.items()
        if not isinstance(name, str)
        or not isinstance(lifetime, ParameterLifetime)
    ]
    if invalid_values:
        names = ", ".join(sorted(map(str, invalid_values)))
        raise TypeError(f"invalid parameter lifetime contracts: {names}")
    # Contracts bind names, not annotation values. A later class/alias may not
    # exist yet while this decorator runs during module or class creation.
    invalid_names = values.keys() - _parameter_names(target)
    if invalid_names:
        names = ", ".join(sorted(invalid_names))
        raise TypeError(f"parameter lifetime parameters do not exist: {names}")
    if (
        isinstance(current, AnalysisDecoration)
        and current.parameter_lifetimes is not None
        and current.parameter_lifetimes != values
    ):
        raise TypeError(
            f"{target.__qualname__!r} already has a parameter lifetime contract."
        )
    return _configure_analysis(
        obj,
        parameter_lifetimes=MappingProxyType(values) if values else None,
    )


def parameter_lifetimes(obj) -> Mapping[str, ParameterLifetime]:
    target = getattr(obj, "__func__", obj)
    decoration = getattr(target, "__dict__", {}).get("__pyjs_analysis__")
    if not isinstance(decoration, AnalysisDecoration):
        return _EMPTY_PARAMETER_LIFETIMES
    return decoration.parameter_lifetimes or _EMPTY_PARAMETER_LIFETIMES


def analysis_metadata(obj, name: str, default=None):
    target = getattr(obj, "__func__", obj)
    decoration = getattr(target, "__dict__", {}).get("__pyjs_analysis__")
    if not isinstance(decoration, AnalysisDecoration):
        return default
    return getattr(decoration, name, default)


def preserves_numeric_format(obj):
    """Declare that a numeric call result keeps its receiver representation."""
    return _configure_analysis(obj, preserves_numeric_format=True)


def integer_index_parameters(*parameters: str):
    """Declare parameters consumed through Python's integer-index protocol."""
    if (
        not parameters
        or any(type(name) is not str or not name for name in parameters)
        or len(parameters) != len(set(parameters))
    ):
        raise TypeError("integer-index parameters require unique names")

    def decorate(obj):
        target = getattr(obj, "__func__", obj)
        if not inspect.isfunction(target):
            raise TypeError("integer-index parameters require a function")
        invalid = set(parameters) - _parameter_names(target)
        if invalid:
            names = ", ".join(sorted(invalid))
            raise TypeError(f"integer-index parameters do not exist: {names}")
        return _configure_analysis(
            obj,
            integer_index_parameters=parameters,
        )

    return decorate


def own_js_metadata(obj, name: str, default=None):
    decoration = own_js_decoration(obj)
    if decoration is None:
        return default
    value = getattr(decoration, name)
    return default if value is None else value


def is_js_enabled(obj) -> bool | None:
    return js_metadata(obj, "enabled")


def get_wgsl_decoration(obj) -> WGSLDecoration | None:
    decoration = getattr(obj, "__wgsl__", None)
    return decoration if isinstance(decoration, WGSLDecoration) else None


def get_native_decoration(obj) -> NativeDecoration | None:
    decoration = getattr(obj, "__native__", None)
    return decoration if isinstance(decoration, NativeDecoration) else None


def native_operation(
    operation: str,
    constant: str | None = None,
    /,
    **lifetimes: ParameterLifetime,
):
    """Declare a Python API operation implemented by the native runtime."""
    if not isinstance(operation, str) or not operation:
        raise TypeError("a native operation requires a non-empty name")
    if constant is not None and not isinstance(constant, str):
        raise TypeError("a native operation constant must be a string")

    def decorate(target):
        if not is_cls_or_func(target):
            raise TypeError("native operations require a function or class")
        if lifetimes and not inspect.isfunction(target):
            raise TypeError("native lifetime contracts require a function")
        existing = get_native_decoration(target)
        decoration = NativeDecoration(operation=operation, constant=constant)
        if existing is not None and existing != decoration:
            raise TypeError(f"{target.__qualname__!r} already has a native operation")
        target.__native__ = decoration
        if lifetimes:
            configure_parameter_lifetimes(target, lifetimes)
        return target

    return decorate


def is_cls_or_func(obj):
    return inspect.isfunction(obj) or inspect.isclass(obj)


def is_declaration(obj, target: str) -> bool:
    obj = getattr(obj, "__func__", obj)
    decoration = getattr(obj, "__dict__", {}).get(f"__{target}__")
    return bool(getattr(decoration, "declaration", False))


def _implementation_kind(obj, target: str) -> str | None:
    obj = getattr(obj, "__func__", obj)
    decoration = getattr(obj, "__dict__", {}).get(f"__{target}__")
    return getattr(decoration, "kind", None)


def is_inline_for(obj, target: str) -> bool:
    return _implementation_kind(obj, target) in {"inline", "call"}


def is_empty_inline(obj, target: str) -> bool:
    obj = getattr(obj, "__func__", obj)
    decoration = getattr(obj, "__dict__", {}).get(f"__{target}__")
    return (
        getattr(decoration, "kind", None) == "inline"
        and getattr(decoration, "template", None) == ""
    )


def is_native_for(obj, target: str) -> bool:
    return _implementation_kind(obj, target) == "native"


def _compiled_callable(function) -> bool:
    while isinstance(function, partial):
        function = function.func
    return is_js_enabled(function) is True


def _callable_implementation(function, field, name, implementation):
    if not callable(implementation):
        raise TypeError(f"@{function.__name__}.{name} requires a callable.")
    declared = own_js_metadata(function, "implementation")
    if field == "client" and declared is not None:
        raise TypeError(
            f"{function.__qualname__!r} already has a JavaScript "
            f"{declared.kind} implementation."
        )
    if field == "client":
        # Shared analysis uses the alternate client function as its source
        # body.  Preserve declarations for other backends on that function so
        # selecting a JavaScript implementation does not silently discard the
        # public callable's target-neutral or backend contracts.
        preserved = []
        for attribute in sorted(DECORATIONS - {"__js__"}):
            value = getattr(function, "__dict__", {}).get(attribute)
            if value is None:
                continue
            existing = getattr(implementation, "__dict__", {}).get(attribute)
            if existing is not None and existing != value:
                raise TypeError(
                    f"{implementation.__qualname__!r} conflicts with "
                    f"{function.__qualname__!r} metadata {attribute!r}."
                )
            preserved.append((attribute, value))
    else:
        preserved = []
    _set_js_field(function, field, implementation, f"JavaScript {name}")
    for attribute, value in preserved:
        setattr(implementation, attribute, value)
    return function


def _bound_inline(function, implementation=None, **references):
    if implementation is None:
        if not references:
            raise TypeError(f"@{function.__name__}.inline requires a callable.")
        return partial(_bound_inline, function, **references)
    if _compiled_callable(implementation):
        raise TypeError(
            "An inline source generator cannot be marked @js. "
            "Use @js.inline(call=helper) to call a runtime helper."
        )
    if not callable(implementation):
        raise TypeError(f"@{function.__name__}.inline requires a callable.")
    _set_inline(function, implementation)
    _copy_js_references(function, implementation)
    if references:
        js.references(**references)(function)
    _validate_inline_references(function)
    return function


def _value_implementation(function, implementation):
    if not inspect.isfunction(implementation):
        raise TypeError(f"@{function.__name__}.value requires a function.")
    js(implementation)
    _set_js_field(
        function,
        "value",
        JSImplementation("function", implementation),
        "a JavaScript value implementation",
    )
    return function


def _value_source(function, source: str):
    if not isinstance(source, str):
        raise TypeError("A value source implementation must be a string.")
    _set_js_field(
        function,
        "value",
        JSImplementation("source", source),
        "a JavaScript value implementation",
    )
    return function


def _analysis_implementation(function, implementation):
    if _compiled_callable(implementation):
        raise TypeError(
            "A call-analysis hook cannot be marked @js because it runs only "
            "in the compiler."
        )
    return _callable_implementation(
        function,
        "analysis",
        "analyze",
        implementation,
    )


def _source_implementation(function, source):
    if not isinstance(source, str) and not callable(source):
        raise TypeError(
            "A JavaScript source implementation must be a string or callable."
        )
    _set_js_implementation(function, JSImplementation("source", source))
    return function


def _attach_implementation_api(function):
    if "client" not in function.__dict__:
        function.client = partial(
            _callable_implementation,
            function,
            "client",
            "client",
        )
    if "inline" not in function.__dict__:
        function.inline = partial(_bound_inline, function)
    if "value" not in function.__dict__:
        value = partial(_value_implementation, function)
        value.source = partial(_value_source, function)
        function.value = value
    if "analyze" not in function.__dict__:
        function.analyze = partial(_analysis_implementation, function)
    function.source = partial(_source_implementation, function)


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


def _prepare_class(cls: type) -> None:
    if "__pyjs_instance_annotations__" not in vars(cls):
        cls.__pyjs_instance_annotations__ = _class_instance_annotations(cls)


def wgsl(obj):
    """Emit a Python function or value class as WGSL."""
    if not is_cls_or_func(obj):
        raise TypeError("@wgsl requires a function or class.")
    if inspect.isfunction(obj):
        obj = _wgsl_python_boundary(obj)
    obj = js(obj)
    _set_backend_decoration(obj, "wgsl", WGSLDecoration("emit"))
    return obj


def _wgsl_python_boundary(function):
    wrapper_names = {
        "ClassVar",
        "Final",
        "NotRequired",
        "ReadOnly",
        "Required",
    }

    def unwrap(annotation):
        while True:
            if isinstance(annotation, str):
                annotation = annotationlib.ForwardRef(
                    annotation,
                    module=function.__module__,
                    owner=function,
                )
            if isinstance(annotation, annotationlib.ForwardRef):
                annotation = annotation.evaluate(
                    globals=function.__globals__,
                    owner=function,
                )
                continue
            if isinstance(annotation, TypeAliasType):
                annotation = annotation.__value__
                continue
            origin = get_origin(annotation)
            if origin is Annotated or (
                origin is not None
                and getattr(origin, "__name__", "") in wrapper_names
            ):
                annotation = get_args(annotation)[0]
                continue
            return annotation

    def converter(annotation):
        annotation = unwrap(annotation)
        numeric = getattr(annotation, "__pyjs_numeric_format__", None)
        if numeric is None or numeric.domain != "wgsl":
            return None
        return annotation

    signature = inspect.signature(
        function,
        annotation_format=annotationlib.Format.STRING,
    )
    parameters = tuple(signature.parameters)
    converters = None

    def resolve_converters():
        nonlocal converters
        if converters is None:
            try:
                annotations = annotationlib.get_annotations(function)
                resolved = (
                    tuple(converter(annotations.get(name)) for name in parameters),
                    converter(annotations.get("return")),
                )
            except NameError:
                return (None,) * len(parameters), None
            converters = resolved
        return converters

    @wraps(function)
    def wrapped(*args, **kwargs):
        parameter_converters, return_converter = resolve_converters()
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        for name, convert in zip(parameters, parameter_converters, strict=True):
            if convert is None or name not in bound.arguments:
                continue
            value = bound.arguments[name]
            if not isinstance(value, convert):
                bound.arguments[name] = convert(value)
        result = function(*bound.args, **bound.kwargs)
        if return_converter is not None and not isinstance(result, return_converter):
            result = return_converter(result)
        return result

    return wrapped


def _wgsl_native(obj):
    """Use the Python body on CPUs and the same-named WGSL builtin on GPUs."""
    if not is_cls_or_func(obj):
        raise TypeError("@wgsl.native requires a function or class.")
    obj = js(obj)
    _set_backend_decoration(obj, "wgsl", WGSLDecoration("native"))
    return obj


def _jvm_native(
    owner: str,
    *,
    name: str | None = None,
    invocation: Literal["static", "virtual"] = "static",
    interface: bool = False,
):
    """Bind a typed fallback function to one static JVM runtime method."""
    if not isinstance(owner, str) or JVM_INTERNAL_NAME.fullmatch(owner) is None:
        raise TypeError("@jvm.native owner must be a valid JVM internal name.")
    if name is not None and (not isinstance(name, str) or not name):
        raise TypeError("@jvm.native name must be a non-empty string.")
    if invocation not in {"static", "virtual"}:
        raise TypeError("@jvm.native invocation is not supported.")
    if not isinstance(interface, bool):
        raise TypeError("@jvm.native interface must be a bool.")

    def decorate(target):
        if not is_cls_or_func(target):
            raise TypeError("@jvm.native requires a function or class.")
        if interface and not inspect.isclass(target) and invocation != "static":
            raise TypeError("@jvm.native interface functions require static invocation.")
        _set_backend_decoration(
            target,
            "jvm",
            JVMDecoration("native", owner, name, invocation, interface),
        )
        return target

    return decorate


def _jvm_field(*, name: str | None = None, writable: bool = True) -> JVMField:
    """Describe one field inside a native JVM class annotation."""
    if name is not None and (not isinstance(name, str) or not name):
        raise TypeError("jvm.field name must be a non-empty string.")
    if not isinstance(writable, bool):
        raise TypeError("jvm.field writable must be a bool.")
    return JVMField(name, writable)


def js(obj):
    """Mark a class or function as reachable by transpiled client code."""
    configure_js(obj, enabled=True)
    if inspect.isclass(obj):
        _prepare_class(obj)
    else:
        _attach_implementation_api(obj)
    return obj


def _set_js_field(target, field, value, description):
    current = own_js_metadata(target, field)
    if current is not None and current != value:
        raise TypeError(f"{target.__qualname__!r} already has {description}.")
    configure_js(target, **{field: value})


def _set_js_implementation(target, implementation: JSImplementation):
    if own_js_metadata(target, "client") is not None:
        raise TypeError(
            f"{target.__qualname__!r} already has a JavaScript client "
            "implementation."
        )
    current = own_js_metadata(target, "implementation")
    if current is not None and current != implementation:
        raise TypeError(
            f"{target.__qualname__!r} already has a JavaScript "
            f"{current.kind} implementation."
        )
    configure_js(target, implementation=implementation)


def _set_backend_decoration(target, backend: str, decoration):
    attribute = f"__{backend}__"
    current = getattr(target, "__dict__", {}).get(attribute)
    if current is not None and current != decoration:
        raise TypeError(
            f"{target.__qualname__!r} already has a {backend.upper()} "
            f"{current.kind} implementation."
        )
    setattr(target, attribute, decoration)


def _set_inline(target, source):
    if isinstance(source, str):
        template = source.replace("{*args}", "{_args_suffix}")
        rewrite = template.format
    elif callable(source):
        if _compiled_callable(source):
            raise TypeError(
                "An @js.inline source generator cannot be marked @js. "
                "Use @js.inline(call=helper) to call a runtime helper."
            )
        rewrite = source
    else:
        raise TypeError("@js.inline requires a source string or callable.")

    _set_js_implementation(target, JSImplementation("inline", rewrite))


def _js_inline(source=None, *, call=None, **references):
    """Replace calls with generated JavaScript and bind named references."""
    if (source is None) == (call is None):
        raise TypeError("@js.inline requires exactly one of source or call.")
    if call is not None:
        if references:
            raise TypeError("@js.inline(call=...) does not accept references.")
        if not inspect.isfunction(call):
            raise TypeError("@js.inline call target must be a function marked @js.")
        if is_js_enabled(call) is not True:
            raise TypeError("@js.inline call target must be marked @js.")
        if is_inline_for(call, "js"):
            raise TypeError("@js.inline call target must emit a runtime function.")

    def decorate(obj):
        if inspect.isclass(obj) and call is not None:
            raise TypeError(
                "Class-level @js.inline does not support call=; use an "
                "inline source expression."
            )
        obj = js(obj)
        if call is not None:
            _set_js_implementation(obj, JSImplementation("call", call))
        else:
            _set_inline(obj, source)
            if callable(source):
                _copy_js_references(obj, source)
        if references:
            js.references(**references)(obj)
        _validate_inline_references(obj)
        return obj

    return decorate


def _reference_mapping(references, named_references):
    resolved = dict(named_references)
    for reference in references:
        name = getattr(reference, "__name__", None)
        if name is None:
            raise TypeError("JavaScript references must be classes or functions.")
        previous = resolved.get(name)
        if previous is not None and previous is not reference:
            raise TypeError(
                f"JavaScript reference name {name!r} is already assigned."
            )
        resolved[name] = reference
    # Dollar-prefixed names are used by generated JavaScript to avoid
    # colliding with names written by the application.
    invalid = [
        (name, type(reference).__name__)
        for name, reference in resolved.items()
        if not isinstance(name, str)
        or not (
            name.isidentifier()
            or name.startswith("$") and name[1:].isidentifier()
        )
        or not is_cls_or_func(reference)
    ]
    if invalid:
        values = ", ".join(f"{name!r} ({type_name})" for name, type_name in invalid)
        raise TypeError(
            "JavaScript references require identifier names and class or function "
            f"values; invalid: {values}."
        )
    return resolved


def _set_js_references(target, references):
    current = dict(own_js_metadata(target, "references", {}))
    for name, reference in references.items():
        previous = current.get(name)
        if previous is not None and previous is not reference:
            raise TypeError(
                f"{target.__qualname__!r} already assigns JavaScript reference "
                f"{name!r}."
            )
        current[name] = reference
    configure_js(target, references=current)
    return target


def _copy_js_references(target, source):
    references = backend_references(source, "js")
    if references:
        _set_js_references(target, references)


def _validate_inline_references(target):
    references = backend_references(target, "js")
    if not references:
        return
    reserved = {
        "_arg_strs",
        "_arg_types",
        "_arg_formats",
        "_arg_representations",
        "_arg_item_representations",
        "_arg_item_formats",
        "_keyword_strs",
        "_args_joined",
        "_args_suffix",
        "self",
        "_self_format",
        "_result_format",
    }
    conflicts = set(references) & (reserved | set(_parameter_names(target)))
    if conflicts:
        raise TypeError(
            f"@js.inline reference names for {target.__qualname__!r} conflict "
            f"with call arguments: {', '.join(sorted(conflicts))}."
        )


def _js_references(*references, **named_references):
    """Declare names used by JavaScript source that Python cannot analyze."""
    resolved = _reference_mapping(references, named_references)

    def decorate(target):
        if not is_cls_or_func(target):
            raise TypeError("@js.references requires a function or class.")
        return _set_js_references(target, resolved)

    return decorate


def _js_native(obj):
    if is_cls_or_func(obj):
        obj = js(obj)
    else:
        configure_js(obj, enabled=True)
        obj.__static__ = True
    obj.__builtin__ = True
    _set_js_implementation(obj, JSImplementation("native"))
    return obj


def _js_runtime(runtime_type: type):
    if not inspect.isclass(runtime_type):
        raise TypeError("@js.runtime requires a runtime class.")

    def decorate(cls):
        if not inspect.isclass(cls):
            raise TypeError("@js.runtime is only supported for classes.")
        return configure_js(cls, runtime_type=runtime_type)

    return decorate


def _js_dictionary(cls):
    if not inspect.isclass(cls):
        raise TypeError("@js.dictionary is only supported for classes.")
    cls = js(cls)
    return configure_js(cls, dictionary=True)


def _js_keep(obj):
    if inspect.isclass(obj) or "." not in obj.__qualname__:
        raise TypeError("@js.keep is only supported for class methods.")
    obj = js(obj)
    return configure_js(obj, keep=True)


def _js_dispatch(method_name: str):
    if not (
        isinstance(method_name, str)
        and method_name.startswith("__")
        and method_name.endswith("__")
    ):
        raise TypeError("@js.dispatch requires a dunder method name.")

    def decorate(obj):
        obj = js(obj)
        return configure_js(obj, dispatch=method_name)

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
        return configure_js(obj, runtime_dunders=(item_of, method_names))

    return decorate


def nojs(cls_func):
    return configure_js(cls_func, enabled=False)


def _wgsl_inline(source: str):
    """Replace calls with a WGSL expression using parameter placeholders."""
    if not isinstance(source, str):
        raise TypeError("@wgsl.inline requires a source string.")

    def decorate(target):
        if not inspect.isfunction(target):
            raise TypeError("@wgsl.inline requires a function.")
        target = js(target)
        _set_backend_decoration(
            target,
            "wgsl",
            WGSLDecoration("inline", template=source),
        )
        return target

    return decorate


wgsl.native = _wgsl_native
wgsl.inline = _wgsl_inline


class _JVMDecorators:
    native = staticmethod(_jvm_native)
    field = staticmethod(_jvm_field)


jvm = _JVMDecorators()

js.inline = _js_inline
js.references = _js_references
js.native = _js_native
js.runtime = _js_runtime
js.dictionary = _js_dictionary
js.keep = _js_keep
js.dispatch = _js_dispatch
js.runtime_dunders = _js_runtime_dunders


type JS[T] = Annotated[T, js]


class _LLVMDecorators:
    @staticmethod
    def inline(template: str, /, **lifetimes: ParameterLifetime):
        """Substitute a typed LLVM expression; an empty template erases the call.

        Erasure skips receiver evaluation and argument evaluation and analysis.
        A parameter-only template evaluates that operand without an instruction.
        The Python implementation remains the CPython fallback.
        """
        if not isinstance(template, str) or "\n" in template:
            raise TypeError("an LLVM inline expression must be a single-line string")

        def decorate(target):
            if not inspect.isfunction(target):
                raise TypeError("@llvm.inline requires a function")
            parameters = _parameter_names(target)
            for _literal, field, specification, conversion in string.Formatter().parse(template):
                if field is None:
                    continue
                if field not in parameters:
                    raise TypeError(
                        f"LLVM inline placeholder {field!r} is not a parameter of "
                        f"{target.__qualname__}"
                    )
                if specification or conversion:
                    raise TypeError(
                        "LLVM inline placeholders do not accept conversions or formats"
                    )
            _set_backend_decoration(target, "native", NativeDecoration(
                kind="inline", template=template,
            ))
            if lifetimes:
                configure_parameter_lifetimes(target, lifetimes)
            return target

        return decorate


llvm = _LLVMDecorators()
