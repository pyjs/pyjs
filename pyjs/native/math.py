"""Native math validation compiled from Python; scalar leaves use LLVM/libm."""

import ast
import inspect
import math
from collections.abc import Iterable
from functools import partial

from pyjs.decorators import configure_js, native_operation
from pyjs.native.runtime import math_calls as _calls
from pyjs.native.runtime.float_math import absolute, copy_sign

from .errors import LLVMUnsupported
from .functional import reduce as _reduce  # noqa: F401 -- analyzed dependency of _product
from .math_aggregates import checked_integer as _checked_integer
from .math_aggregates import sumprod as _sumprod
from .operator import index as _index
from .operator import mul as _multiply  # noqa: F401 -- analyzed dependency of _product
from .runtime import wide as _wide

e = math.e
inf = math.inf
nan = math.nan
pi = math.pi
tau = math.tau


@native_operation("math.prod")
def prod(iterable: Iterable[object], /, *, start: object = 1) -> object:
    return math.prod(iterable, start=start)


def _multiply_integer(left: int, right: int) -> int:
    # A product of two signed i64 values fits i128. Check before narrowing;
    # neither division-based checks nor abs() safely handle INT64_MIN.
    result = _wide.multiply(_wide.widen(left), _wide.widen(right))
    return _checked_integer(result, "math.prod")


def _multiply_bool(left: int, right: bool) -> int:
    return _multiply_integer(left, int(right))


def _multiply_numbers(left: int | float, right: int | float) -> int | float:
    # Explicit arms retain Python's integer-to-float transition without asking
    # generic union arithmetic to select one scalar lowering for both domains.
    if isinstance(left, int):
        integer = int(left)
        if isinstance(right, int):
            return _multiply_integer(integer, int(right))
        return integer * right
    if isinstance(right, int):
        return left * int(right)
    return left * right


def _multiply_float(left: float, right: int | float) -> float:
    if isinstance(right, int):
        return left * int(right)
    return left * right


def _product(call):
    from pyjs.analysis.analyzer import (
        BUILTINS,
        InferenceVisitor,
        analyzed_value_object,
        analyzed_value_type,
        get_type_members,
        iterable_is_provably_nonempty,
    )
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.objects import (
        DependencyError,
        EvaluateOnce,
        LocalScope,
        Name,
        UnionType,
    )
    from pyjs.analysis.representation import apply_representation
    from pyjs.analysis.value_representation import (
        analyzed_representation,
        set_analyzed_representation,
    )

    InferenceVisitor.expand_static_call_keywords(call.visitor, call.node)
    if any(isinstance(value, ast.Starred) for value in call.node.args) or any(
        keyword.arg is None for keyword in call.node.keywords
    ):
        raise LLVMUnsupported("native math.prod requires explicit iterable and start arguments", call.node)
    call.visitor.validate_call_shape(call.node, call.function)
    visitor = call.visitor.child_visitor(LocalScope(call.visitor.scope))
    empty = isinstance(call.node.args[0], (ast.List, ast.Tuple)) and not call.node.args[0].elts
    values = None if empty else visitor.visit(call.node.args[0])
    start = next((keyword.value for keyword in call.node.keywords if keyword.arg == "start"), None)
    initial_source = start if start is not None else ast.copy_location(ast.Constant(value=1), call.node)
    initial = visitor.visit(initial_source)
    initial_type = analyzed_value_type(initial)
    initial_representation = analyzed_representation(initial)
    if empty:
        # Empty literals have no child effects and keep even nonnumeric starts
        # unchanged. No concrete item storage or numeric callback is needed.
        return initial

    protocol = visitor.require_iterable(call.node.args[0], values)
    nonempty = iterable_is_provably_nonempty(call.node.args[0], values)
    ordinary = {BUILTINS.search(name) for name in ("int", "float", "bool")}
    if any(member not in ordinary for semantic in (initial_type, protocol.item_type)
           for member in get_type_members(semantic)):
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native math.prod requires numeric items and a numeric start")
    representation = protocol.item_representation
    if (start is None and representation is not None and representation.numeric is not None
            and nonempty):
        # A proven first item changes the ordinary identity to its portable
        # domain. One is exactly representable; empty sources must keep int(1).
        identity = ast.copy_location(ast.Constant(
            value=1.0 if representation.numeric.kind == "float" else 1), call.node)
        initial = visitor.normalize_numeric_value(visitor.visit(identity), representation.numeric, force=True)
        initial_type = analyzed_value_type(initial)
        initial_representation = analyzed_representation(initial)
    floating_start = (initial_type is BUILTINS.search("float") and initial_representation is None
                      and representation is not None and representation.numeric is not None
                      and representation.numeric.kind == "integer")
    if representation != initial_representation and not floating_start:
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native math.prod requires matching item and start representations",
                          help="Supply start using the iterable's fixed-width numeric type.")

    scope = call.function.container.scope
    reduction = scope.search("_reduce")
    if not reduction.is_analyzed:
        raise DependencyError(reduction)
    visitor.scope.add(reduction, "$prod_reduce")
    bindings = [(values, "$prod_values"), (initial, "$prod_start")]
    for value, name in bindings:
        instance = analyzed_value_type(value)(name, visitor.scope, visitor.func)
        apply_representation(instance, analyzed_representation(value))
        visitor.scope.add(instance)
    mixed = (isinstance(initial_type, UnionType) or isinstance(protocol.item_type, UnionType)
             or initial_type is BUILTINS.search("bool")
             or initial_type is BUILTINS.search("int") and protocol.item_type is BUILTINS.search("float"))
    name = "_multiply"
    if mixed:
        name = "_multiply_float" if initial_type is BUILTINS.search("float") else "_multiply_numbers"
    elif initial_type is BUILTINS.search("int") and representation is None:
        name = "_multiply_bool" if protocol.item_type is BUILTINS.search("bool") else "_multiply_integer"
    multiplication = scope.search(name)
    if not multiplication.is_analyzed:
        raise DependencyError(multiplication)
    visitor.scope.add(multiplication, "$prod_multiply")
    # operator.mul specializes portable wrapping/rounding and float arithmetic.
    # Ordinary integers instead use the math module's checked-width contract.
    callback = ast.Name(id="$prod_multiply", ctx=ast.Load())
    result = visitor.visit(ast.fix_missing_locations(ast.copy_location(ast.Call(
        func=ast.Name(id="$prod_reduce", ctx=ast.Load()),
        args=[callback, *(ast.Name(id=name, ctx=ast.Load()) for _, name in bindings)], keywords=[],
    ), call.node)))
    if mixed and nonempty:
        # Expose a scalar result when a first multiplication proves its kind.
        # Convert after reduction, not before: an integer prefix must remain
        # exact until the first float item actually arrives.
        scalar = ("float" if protocol.item_type is BUILTINS.search("float") else
                  "int" if initial_type is BUILTINS.search("bool") and
                  protocol.item_type in {BUILTINS.search("int"), BUILTINS.search("bool")} else None)
        if scalar is not None:
            target = BUILTINS.search(scalar)
            result = visitor.call_node(call.node, target, func=Name(target, ctx=ast.Load()),
                                       args=[result], keywords=[])
    # Analyze each argument once and bind both before obtaining an iterator.
    # The lexical bindings also root temporary sources through start callbacks.
    for value, name in reversed(bindings):
        result_representation = analyzed_representation(result)
        result = EvaluateOnce(analyzed_value_object(result), value, result, name, lineno=call.node.lineno)
        set_analyzed_representation(result, result_representation)
    return result


configure_js(prod, analysis=_product)


def sumprod(p: Iterable[int | float], q: Iterable[int | float], /) -> int | float:
    return _sumprod(p, q)


def _paired_product(call):
    from pyjs.analysis.analyzer import (
        BUILTINS,
        InferenceVisitor,
        get_type_members,
        iterable_is_provably_nonempty,
    )
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.iterable_protocol import retain_iterable_conversion
    from pyjs.analysis.objects import Name

    InferenceVisitor.expand_static_call_keywords(call.visitor, call.node)
    if any(isinstance(value, ast.Starred) for value in call.node.args):
        raise LLVMUnsupported("native math.sumprod requires two explicit iterable arguments", call.node)
    result = call.standard()
    integers = {BUILTINS.search("int"), BUILTINS.search("bool")}
    ordinary = integers | {BUILTINS.search("float")}
    protocols = []
    nonempty_float = False
    for parameter, source, value in zip(call.function.params, call.node.args, result.args, strict=True):
        if isinstance(source, (ast.List, ast.Tuple)) and not source.elts:
            # The iterable API supplies a concrete layout for a fresh empty
            # literal. Still create/advance both iterators for observable effects.
            name = "list" if isinstance(source, ast.List) else "tuple"
            semantic = BUILTINS.search(name)(BUILTINS.search("int"),
                                           **({"tuple_variadic": True} if name == "tuple" else {}))
            call.visitor.apply_literal_type(value, semantic)
        protocol = call.visitor.require_iterable(source, value)
        if (protocol.item_representation is not None
                or any(member not in ordinary for member in get_type_members(protocol.item_type))):
            call.visitor.fail(source, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "native math.sumprod requires ordinary int, bool or float items",
                              help="Convert portable numeric items explicitly with int() or float().")
        # Custom analysis owns argument normalization even after standard().
        # Preserve each source's iterable adapter and cursor dependencies while
        # analyzer retries can still resolve newly specialized signatures.
        retain_iterable_conversion(value, parameter.annotation.obj)
        protocols.append(protocol)
        nonempty_float |= (protocol.item_type is BUILTINS.search("float")
                           and iterable_is_provably_nonempty(source, value))
    # Pure integer pairs always return int. A proven floating pair returns float;
    # otherwise the empty-input int(0) identity requires the union result.
    scalar = ("int" if all(member in integers for protocol in protocols
                           for member in get_type_members(protocol.item_type)) else
              "float" if nonempty_float else None)
    if scalar is not None:
        target = BUILTINS.search(scalar)
        result = call.visitor.call_node(call.node, target, func=Name(target, ctx=ast.Load()),
                                        args=[result], keywords=[])
    return result


configure_js(sumprod, analysis=_paired_product)


@native_operation("math.fsum")
def fsum(values: Iterable[object], /) -> float:
    return math.fsum(values)


@native_operation("math.dist")
def dist(p: Iterable[object], q: Iterable[object], /) -> float:
    return math.dist(p, q)


def _numeric_iterables(call):
    # These APIs explicitly convert each item to ordinary float. Preserve
    # represented source containers until the native item conversion; their
    # storage must not be normalized as an Iterable[object] argument.
    return call.standard(defer_representation_arguments=tuple(range(len(call.node.args))))


configure_js(fsum, analysis=_numeric_iterables)
configure_js(dist, analysis=_numeric_iterables)


def _coerce_arguments(call, positional, named, variadic, *, rounding, logarithm):
    from pyjs.analysis.analyzer import BUILTINS, InferenceVisitor, analyzed_value_type
    from pyjs.analysis.objects import Name

    # Coercion needs statically known destinations. Keep the shared literal
    # keyword expansion even though native application calls merge at runtime.
    InferenceVisitor.expand_static_call_keywords(call.visitor, call.node)
    if any(isinstance(argument, ast.Starred) for argument in call.node.args) or any(
        keyword.arg is None for keyword in call.node.keywords
    ):
        raise LLVMUnsupported("native math argument unpacking requires statically known parameters", call.node)
    result = call.standard(defer_representation_arguments=tuple(range(len(call.node.args))))

    def convert(value, kind):
        # Union-typed parameters keep their alternatives for the Python wrapper
        # to validate (for example nextafter's None/Boolean step count).
        if kind not in (int, float):
            return value
        target = BUILTINS.search(kind.__name__)
        return call.visitor.call_node(value, target, func=Name(target, ctx=ast.Load()),
                                      args=[value], keywords=[])

    if rounding and result.args:
        if analyzed_value_type(result.args[0]).generic_name in {"int", "bool"}:
            target = BUILTINS.search("int")
            return call.visitor.call_node(result, target, func=Name(target, ctx=ast.Load()),
                                          args=result.args, keywords=[])
    integer_arguments = [analyzed_value_type(value).generic_name in {"int", "bool"}
                         for value in result.args] if logarithm else []
    result.args = [convert(value, positional[index] if index < len(positional) else variadic)
                   for index, value in enumerate(result.args)]
    for keyword in result.keywords:
        keyword.value = convert(keyword.value, named[keyword.arg])
    if logarithm:
        # Preserve the input kinds through float coercion without validating
        # early: Python evaluates every argument before checking either domain.
        target = result.func.obj
        missing = len(target.params) - len(result.args)
        if missing:
            result.args.extend(target.defaults[-missing:])
            integer_arguments.extend([False] * missing)
        result.args.extend(call.visitor.visit(ast.Constant(value=value)) for value in integer_arguments)
        implementation = target.container.scope.search("_" + target.name)
        result.func = Name(implementation, runtime_dependency=implementation, ctx=ast.Load())
    return result


def _math_arguments(function=None, *, rounding=False, logarithm=False):
    if function is None:
        return partial(_math_arguments, rounding=rounding, logarithm=logarithm)
    signature = inspect.signature(function)
    positional = tuple(parameter.annotation for parameter in signature.parameters.values()
                       if parameter.kind in {parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD})
    named = {name: parameter.annotation for name, parameter in signature.parameters.items()}
    variadic = next((parameter.annotation for parameter in signature.parameters.values()
                     if parameter.kind == parameter.VAR_POSITIONAL), None)
    # Math's numeric conversion is an API semantic, not an annotation rule.
    # Record it as ordinary builtin calls before native ABI emission.
    configure_js(function, analysis=partial(_coerce_arguments, positional=positional,
                                           named=named, variadic=variadic, rounding=rounding,
                                           logarithm=logarithm))
    return function


@_math_arguments(logarithm=True)
def log(value: float, base: float = 2.718281828459045, /) -> float:
    return _log(value, base, False, False)


def _log_input(value: float, integer: bool) -> None:
    if value <= 0.0:
        if integer:
            raise ValueError("expected a positive input")
        raise ValueError("expected a positive input, got " + str(value))


def _log(value: float, base: float, integer_value: bool, integer_base: bool) -> float:
    _log_input(value, integer_value)
    _log_input(base, integer_base)
    return _calls.log(value) / _calls.log(base)


def _integer_arguments(call):
    from pyjs.analysis.analyzer import BUILTINS, InferenceVisitor, analyzed_value_type
    from pyjs.analysis.objects import Constant, DependencyError, EvaluateOnce, IfExp, Name
    from pyjs.analysis.value_representation import (
        analyzed_representation,
        set_analyzed_representation,
    )

    InferenceVisitor.expand_static_call_keywords(call.visitor, call.node)
    if any(isinstance(value, ast.Starred) for value in call.node.args) or any(
        keyword.arg is None for keyword in call.node.keywords
    ):
        raise LLVMUnsupported("native math argument unpacking requires statically known parameters", call.node)
    result = call.standard(defer_representation_arguments=tuple(range(len(call.node.args))))
    scope = call.function.container.scope
    implementation, conversion = scope.search("_" + call.function.name), scope.search("_index")
    for dependency in (implementation, conversion):
        if not dependency.is_analyzed:
            raise DependencyError(dependency)
    converted, bindings = [], []
    for position, value in enumerate(result.args):
        semantic = analyzed_value_type(value)
        temporary = Name(semantic(f"$math{position}", call.visitor.scope, call.visitor.func), ctx=ast.Load())
        set_analyzed_representation(temporary, analyzed_representation(value))
        bindings.append((value, temporary.id))
        indexed = call.visitor.call_node(value, BUILTINS.search("int"),
            func=Name(conversion, ctx=ast.Load(), runtime_dependency=conversion), args=[temporary], keywords=[],
            runtime_protocols=((semantic, ("__index__",)),))
        ast.copy_location(indexed, value)
        if call.function.name == "perm" and position == 1:
            optional = implementation.params[1].annotation.obj
            none = Constant(BUILTINS.search("NoneType"), value=None)
            test = call.visitor.analyze_comparison(call.node, temporary, ast.Is(), none, value, none)
            indexed = ast.copy_location(IfExp(optional, optional, test=test, body=none, orelse=indexed), value)
        converted.append(indexed)
    result.func = Name(implementation, ctx=ast.Load(), runtime_dependency=implementation)
    result.args = converted
    # Bind every source argument before any effectful __index__. EvaluateOnce
    # is the existing rooted lexical-let node: no tuple allocation or new pass.
    # Nested math calls safely shadow these names only inside their own binding.
    for value, name in reversed(bindings):
        result = EvaluateOnce(result.obj, value, result, name, lineno=call.node.lineno)
    return result


def _integer_api(function):
    # Public wrappers keep stored function references usable. Direct calls
    # specialize conversion before invoking the paired typed implementation,
    # avoiding object erasure (especially for portable integer arguments).
    configure_js(function, analysis=_integer_arguments)
    return function


@_integer_api
def gcd(*integers: object) -> int:
    return _gcd(*[_index(value) for value in integers])


@_integer_api
def lcm(*integers: object) -> int:
    return _lcm(*[_index(value) for value in integers])


@_integer_api
def isqrt(value: object, /) -> int:
    return _isqrt(_index(value))


@_integer_api
def factorial(value: object, /) -> int:
    return _factorial(_index(value))


@_integer_api
def comb(n: object, k: object, /) -> int:
    return _comb(_index(n), _index(k))


@_integer_api
def perm(n: object, k: object = None, /) -> int:
    return _perm(_index(n), None if k is None else _index(k))


def _gcd(*integers: int) -> int:
    result = 0
    for value in integers:
        result = _calls.gcd(result, value)
    if result < 0:
        raise OverflowError("math.gcd result exceeds native int range")
    return result


def _lcm(*integers: int) -> int:
    for value in integers:
        if value == 0:
            return 0
    result = 1
    for value in integers:
        result = _calls.lcm(result, value)
        if result < 0:
            raise OverflowError("math.lcm result exceeds native int range")
    return result


def _isqrt(value: int, /) -> int:
    if value < 0:
        raise ValueError("isqrt() argument must be nonnegative")
    return _calls.isqrt(value)


def _factorial(value: int, /) -> int:
    if value < 0:
        raise ValueError("factorial() not defined for negative values")
    if value > 20:
        raise OverflowError("math.factorial result exceeds native int range")
    result = 1
    while value > 1:
        result *= value
        value -= 1
    return result


def _comb(n: int, k: int, /) -> int:
    if n < 0:
        raise ValueError("n must be a non-negative integer")
    if k < 0:
        raise ValueError("k must be a non-negative integer")
    result = _calls.combination(n, k, False)
    if result < 0:
        raise OverflowError("math.comb result exceeds native int range")
    return result


def _perm(n: int, k: int | None = None, /) -> int:
    if k is None:
        return _factorial(n)
    if n < 0:
        raise ValueError("n must be a non-negative integer")
    if k < 0:
        raise ValueError("k must be a non-negative integer")
    result = _calls.combination(n, k, True)
    if result < 0:
        raise OverflowError("math.perm result exceeds native int range")
    return result


@native_operation("math.hypot")
def hypot(*coordinates: float) -> float:
    return math.hypot(*coordinates)


def _hypot_arguments(call):
    from .analysis import expands_arguments

    if expands_arguments(call.node):
        # The checked runtime binder converts each expanded coordinate. It
        # also owns materialization/evaluation order; don't rewrite *sources.
        return call.standard(defer_representation_arguments=tuple(range(len(call.node.args))))
    return _coerce_arguments(call, (), {}, float, rounding=False, logarithm=False)


configure_js(hypot, analysis=_hypot_arguments)


@_math_arguments
def nextafter(x: float, y: float, /, *, steps: int | bool | None = 1) -> float:
    count = 1 if steps is None else int(steps)
    if count < 0:
        raise ValueError("steps must be a non-negative integer")
    return _calls.nextafter_steps(x, y, count)


@_math_arguments
def sqrt(value: float, /) -> float:
    if value < 0.0:
        raise ValueError("expected a nonnegative input, got " + str(value))
    return _calls.sqrt(value)


@_math_arguments
def isfinite(value: float, /) -> bool:
    return abs(value) < inf


@_math_arguments
def isclose(
    a: float,
    b: float,
    *,
    rel_tol: float = 1e-9,
    abs_tol: float = 0.0,
) -> bool:
    if rel_tol < 0.0 or abs_tol < 0.0:
        raise ValueError("tolerances must be non-negative")
    if a == b:
        return True
    if isinf(a) or isinf(b):
        return False
    difference = abs(a - b)
    return (difference <= rel_tol * abs(a)
            or difference <= rel_tol * abs(b) or difference <= abs_tol)


@_math_arguments(rounding=True)
def floor(value: float, /) -> int:
    return int(_calls.floor(value))


@_math_arguments(rounding=True)
def ceil(value: float, /) -> int:
    return int(_calls.ceil(value))


@_math_arguments
def sin(value: float, /) -> float:
    if isinf(value):
        raise ValueError("expected a finite input, got " + str(value))
    return _calls.sin(value)


@_math_arguments
def cos(value: float, /) -> float:
    if isinf(value):
        raise ValueError("expected a finite input, got " + str(value))
    return _calls.cos(value)


@_math_arguments
def cosh(value: float, /) -> float:
    result = _calls.cosh(value)
    if isfinite(value) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments
def tan(value: float, /) -> float:
    if isinf(value):
        raise ValueError("expected a finite input, got " + str(value))
    return _calls.tan(value)


@_math_arguments
def asin(value: float, /) -> float:
    if abs(value) > 1.0:
        raise ValueError("expected a number in range from -1 up to 1, got " + str(value))
    return _calls.asin(value)


@_math_arguments
def acos(value: float, /) -> float:
    if abs(value) > 1.0:
        raise ValueError("expected a number in range from -1 up to 1, got " + str(value))
    return _calls.acos(value)


@_math_arguments
def acosh(value: float, /) -> float:
    if value < 1.0:
        raise ValueError("expected argument value not less than 1, got " + str(value))
    return _calls.acosh(value)


@_math_arguments
def asinh(value: float, /) -> float:
    return _calls.asinh(value)


@_math_arguments
def atan(value: float, /) -> float:
    return _calls.atan(value)


@_math_arguments
def atan2(y: float, x: float, /) -> float:
    return _calls.atan2(y, x)


@_math_arguments
def atanh(value: float, /) -> float:
    if abs(value) >= 1.0:
        raise ValueError("expected a number between -1 and 1, got " + str(value))
    return _calls.atanh(value)


@_math_arguments
def cbrt(value: float, /) -> float:
    return _calls.cbrt(value)


@_math_arguments
def exp(value: float, /) -> float:
    result = _calls.exp(value)
    if isfinite(value) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments
def exp2(value: float, /) -> float:
    result = _calls.exp2(value)
    if isfinite(value) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments
def expm1(value: float, /) -> float:
    result = _calls.expm1(value)
    if isfinite(value) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments(logarithm=True)
def log2(value: float, /) -> float:
    return _log2(value, False)


def _log2(value: float, integer: bool) -> float:
    _log_input(value, integer)
    return _calls.log2(value)


@_math_arguments(logarithm=True)
def log10(value: float, /) -> float:
    return _log10(value, False)


def _log10(value: float, integer: bool) -> float:
    _log_input(value, integer)
    return _calls.log10(value)


@_math_arguments
def log1p(value: float, /) -> float:
    if value <= -1.0:
        raise ValueError("expected argument value > -1, got " + str(value))
    return _calls.log1p(value)


@_math_arguments
def fabs(value: float, /) -> float:
    return absolute(value)


@_math_arguments
def copysign(magnitude: float, sign: float, /) -> float:
    return copy_sign(magnitude, sign)


@_math_arguments
def radians(value: float, /) -> float:
    return value * 1.7453292519943295e-2


@_math_arguments
def degrees(value: float, /) -> float:
    return value * 5.729577951308232e1


@_math_arguments
def fmod(left: float, right: float, /) -> float:
    if not isnan(left) and not isnan(right) and (isinf(left) or right == 0.0):
        raise ValueError("math domain error")
    return _calls.fmod(left, right)


@_math_arguments
def fma(x: float, y: float, z: float, /) -> float:
    result = _calls.fma(x, y, z)
    if isnan(result) and not (isnan(x) or isnan(y) or isnan(z)):
        raise ValueError("invalid operation in fma")
    if isfinite(x) and isfinite(y) and isfinite(z) and isinf(result):
        raise OverflowError("overflow in fma")
    return result


@_math_arguments
def frexp(value: float, /) -> tuple[float, int]:
    return _calls.frexp(value)


@_math_arguments
def gamma(value: float, /) -> float:
    if (isfinite(value) and value <= 0.0 and value == _calls.trunc(value)) or value == -inf:
        raise ValueError("expected a noninteger or positive integer, got " + str(value))
    result = _calls.gamma(value)
    if isfinite(value) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments
def isinf(value: float, /) -> bool:
    return abs(value) == inf


@_math_arguments
def isnan(value: float, /) -> bool:
    return value != value


@_math_arguments
def pow(left: float, right: float, /) -> float:
    if left == 0.0 and right < 0.0 and isfinite(right):
        raise ValueError("math domain error")
    result = _calls.pow(left, right)
    if isnan(result) and not isnan(left) and not isnan(right):
        raise ValueError("math domain error")
    if isfinite(left) and isfinite(right) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments(rounding=True)
def trunc(value: float, /) -> int:
    return int(_calls.trunc(value))


@_math_arguments
def ldexp(value: float, exponent: int, /) -> float:
    result = _calls.ldexp(value, min(max(exponent, -2147483648), 2147483647))
    if isfinite(value) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments
def lgamma(value: float, /) -> float:
    if (isfinite(value) and value <= 0.0 and value == _calls.trunc(value)):
        raise ValueError("expected a noninteger or positive integer, got " + str(value))
    result = _calls.lgamma(value)
    if isfinite(value) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments
def modf(value: float, /) -> tuple[float, float]:
    return _calls.modf(value)


@_math_arguments
def remainder(left: float, right: float, /) -> float:
    if not isnan(left) and not isnan(right) and (isinf(left) or right == 0.0):
        raise ValueError("math domain error")
    return _calls.remainder(left, right)


@_math_arguments
def erf(value: float, /) -> float:
    return _calls.erf(value)


@_math_arguments
def erfc(value: float, /) -> float:
    return _calls.erfc(value)


@_math_arguments
def tanh(value: float, /) -> float:
    return _calls.tanh(value)


@_math_arguments
def sinh(value: float, /) -> float:
    result = _calls.sinh(value)
    if isfinite(value) and isinf(result):
        raise OverflowError("math range error")
    return result


@_math_arguments
def ulp(value: float, /) -> float:
    value = abs(value)
    if isinf(value):
        return value
    following = _calls.nextafter(value, inf)
    if isinf(following):
        return value - _calls.nextafter(value, 0.0)
    return following - value
