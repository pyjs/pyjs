"""Optional arity is part of the callable type, not a guessed backend ABI."""

import ast

import pytest

from pyjs.analysis.diagnostics import CompilationError, describe_type
from pyjs.analysis.objects import (
    CallableClass,
    same_analyzer_type,
    specialization_cache_key,
)
from pyjs.analysis.source import analyze_source
from pyjs.analysis.type_relations import is_subclass
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
@pytest.mark.parametrize("expression, minimum", [("first", 1), ("second", 2),
                                                 ("first if flag else second", 2)])
def test_callable_default_arity_survives_analysis(environment, expression, minimum):
    options = {"environment": environment} if environment is not None else {}
    with analyze_source(f'''
        from pyjs import js
        @js
        def first(value: int, extra: int = 10) -> int:
            return value + extra
        @js
        def second(value: int, extra: int) -> int:
            return value + extra
        @js
        def main(flag: bool):
            return {expression}
    ''', wrap=False, **options) as analysis:
        result = analysis.entry_point.return_type
        assert isinstance(result, CallableClass)
        assert result.minimum_arguments == minimum
        assert len(result.parameter_types) == 2
        assert [result.accepts_arity(count) for count in range(4)] == [
            False, minimum == 1, True, False,
        ]
        fixed = CallableClass(result.parameter_types, result.return_type, result.super,
                              result.parameter_representations, result.return_representation)
        assert same_analyzer_type(result, fixed) is (minimum == 2)
        assert (specialization_cache_key(result) == specialization_cache_key(fixed)) is (minimum == 2)
        assert is_subclass(result, fixed)
        assert is_subclass(fixed, result) is (minimum == 2)


@pytest.mark.parametrize("signature, invocation, diagnostic", [
    ("value: int, extra: int = 2", "callback()", "Callable expects 1 to 2 arguments, got 0"),
    ("value: int, extra: int = 2", "callback(1, 2, 3)", "Callable expects 1 to 2 arguments, got 3"),
    ("value: int, *, extra: int", "callback(1)", "Callable requires keyword-only arguments: extra"),
])
def test_inferred_callable_reports_unsupported_arguments(signature, invocation, diagnostic):
    with pytest.raises(CompilationError, match=diagnostic):
        analyze_source(f'''
            from pyjs import js
            @js
            def read({signature}) -> int:
                return value + extra
            @js
            def main() -> int:
                callback = read
                return {invocation}
        ''', wrap=False)


@pytest.mark.parametrize("target", ["int16", "int"])
def test_shortened_callable_views_do_not_erase_numeric_parameter_widths(target):
    with pytest.raises(CompilationError, match="representation|Callable|callable|incompatible"):
        analyze_source(f'''
            from collections.abc import Callable
            from pyjs import js, int8, int16
            @js
            def small(value: int8, extra: int8 = 2) -> int8:
                return value + extra
            @js
            def main() -> int:
                callback = small
                view: Callable[[{target}], int8] = callback
                return int(view({target}(1)))
        ''', wrap=False)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("suffix", ["", ', extra: str = "x"', ", extra: int8 = 1"])
def test_union_method_view_keeps_only_common_parameter_prefix(environment, reverse, suffix):
    options = {"environment": environment} if environment is not None else {}
    union = "Right | Left" if reverse else "Left | Right"
    source = f'''
        from pyjs import js, int8
        @js
        class Left:
            def read(self, value: int, extra: int = 1) -> int:
                return value + extra
        @js
        class Right:
            def read(self, value: int{suffix}) -> int:
                return value
        @js
        def main(value: {union}):
            return value.read
    '''
    with analyze_source(source, wrap=False, **options) as analysis:
        signature = analysis.entry_point.return_type
        assert signature.minimum_arguments == 1
        assert len(signature.parameter_types) == 1
        assert [signature.accepts_arity(count) for count in range(3)] == [False, True, False]


def test_union_callbacks_without_a_common_required_prefix_report_a_located_error():
    with pytest.raises(CompilationError, match="no common positional signature"):
        analyze_source('''
            from pyjs import js
            @js
            class Left:
                def read(self, value: int) -> int:
                    return value
            @js
            class Right:
                def read(self, value: str) -> int:
                    return len(value)
            @js
            def main(value: Left | Right) -> int:
                callback = value.read
                return callback(1)
        ''', wrap=False)


@pytest.mark.parametrize("reverse", [False, True])
def test_union_callback_prefix_retains_a_contravariant_common_domain(reverse):
    union = "Right | Left" if reverse else "Left | Right"
    with analyze_source(f'''
        from pyjs import js
        @js
        class Left:
            def read(self, value: object) -> int:
                return 1
        @js
        class Right:
            def read(self, value: str) -> int:
                return len(value)
        @js
        def main(value: {union}):
            return value.read
    ''', wrap=False) as analysis:
        signature = analysis.entry_point.return_type
        assert signature.minimum_arguments == 1
        assert [parameter.name for parameter in signature.parameter_types] == ["str"]


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("reverse", [False, True])
def test_ellipsis_conditional_does_not_promise_default_omission(environment, reverse):
    options = {"environment": environment} if environment is not None else {}
    expression = "opaque() if flag else optional" if reverse else "optional if flag else opaque()"
    with pytest.raises(CompilationError, match="Callable expects 2 arguments, got 1"):
        analyze_source(f'''
            from collections.abc import Callable
            from pyjs import js
            @js
            def optional(value: int, extra: int = 10) -> int:
                return value + extra
            @js
            def strict(value: int, extra: int) -> int:
                return value - extra
            @js
            def opaque() -> Callable[..., int]:
                return strict
            @js
            def main(flag: bool) -> int:
                callback = {expression}
                return callback(4)
        ''', wrap=False, **options)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("body", ["return consume(Box(optional))", "box: Box[Callable[[int], int]] = Box(optional)\n                return consume(box)"])
def test_application_generic_callable_storage_is_invariant(environment, body):
    options = {"environment": environment} if environment is not None else {}
    with pytest.raises(CompilationError, match="incompatible|expects|Expected|Cannot assign") as caught:
        analyze_source(f'''
            from collections.abc import Callable
            from pyjs import js
            @js
            class Box[T]:
                def __init__(self, value: T):
                    self.value = value
                def get(self) -> T:
                    return self.value
            @js
            def optional(value: int = 10) -> int:
                return value + 2
            @js
            def consume(box: Box[Callable[[int], int]]) -> int:
                box.get()
                return 7
            @js
            def main() -> int:
                {body}
        ''', wrap=False, **options)
    assert "T: accepts 0 to 1 positional arguments" in str(caught.value)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("callee", ["named", "local", "parameter"])
@pytest.mark.parametrize("signature, body, expected", [
    ("value: str", '"D" + value', "accepts str, but must accept int"),
    ("value: int, extra: int", 'str(value + extra)', "accepts 1 positional argument"),
    ("value: int, *, extra: int", 'str(value + extra)', "accepts 1 positional argument"),
    ("value: int", "value", "returns int, expected str"),
])
def test_direct_union_callback_arguments_validate_every_method(environment, reverse, callee, signature, body, expected):
    options = {"environment": environment} if environment is not None else {}
    union = "Right | Left" if reverse else "Left | Right"
    returned = "int" if body == "value" else "str"
    extra = ", callback: Callable[[Callable[[int], str]], str]" if callee == "parameter" else ""
    invocation = "use(value.read)" if callee == "named" else "callback(value.read)"
    declaration = "    callback: Callable[[Callable[[int], str]], str] = use\n" if callee == "local" else ""
    source = f'''from collections.abc import Callable
from pyjs import js
@js
class Left:
    def read(self, value: object, extra: int = 1) -> str:
        return str(value)
@js
class Right:
    def read(self, {signature}) -> {returned}:
        return {body}
@js
def use(callback: Callable[[int], str]) -> str:
    return callback(1)
@js
def main(value: {union}{extra}) -> str:
{declaration}    return {invocation}
'''
    with pytest.raises(CompilationError, match=expected) as caught:
        analyze_source(source, filename="union_argument.py", wrap=False, **options)
    assert caught.value.lineno == (17 if callee == "local" else 16)
    assert caught.value.filename == "union_argument.py"


def test_callable_diagnostic_details_do_not_change_annotation_syntax():
    with analyze_source('''
        from pyjs import js
        @js
        def optional(value: int = 10, *, required: str) -> int:
            return value
        @js
        def main():
            return optional
    ''', wrap=False) as analysis:
        signature = analysis.entry_point.return_type
        assert signature.to_annotation_str() == "Callable[[int], int]"
        assert ast.unparse(signature.annotation) == "Callable[[int], int]"
        assert describe_type(signature) == (
            "Callable[[int], int] (accepts 0 to 1 positional arguments; "
            "requires keyword-only arguments: required)"
        )


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("left, right, minimum, prefix", [
    ("value: str", "value: int", 1, 0),
    ("value: int, extra: str = 'x'", "value: int, extra: int", 2, 1),
])
def test_uncallable_union_diagnostic_does_not_invent_an_arity_range(environment, reverse, left, right, minimum, prefix):
    options = {"environment": environment} if environment is not None else {}
    union = "Right | Left" if reverse else "Left | Right"
    with pytest.raises(CompilationError) as caught:
        analyze_source(f'''
            from collections.abc import Callable
            from pyjs import js
            @js
            class Left:
                def read(self, {left}) -> str:
                    return str(value)
            @js
            class Right:
                def read(self, {right}) -> str:
                    return str(value)
            @js
            def main(receiver: {union}) -> str:
                callback: Callable[[int], str] = receiver.read
                return callback(1)
        ''', wrap=False, **options)
    assert f"no compatible positional arity (requires {minimum}, common typed prefix {prefix})" in str(caught.value)
    assert f"accepts {minimum} to {prefix}" not in str(caught.value)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
def test_class_valued_attribute_is_a_located_unsupported_boundary(environment):
    options = {"environment": environment} if environment is not None else {}
    with pytest.raises(CompilationError, match="Class-valued attribute 'alias' is not supported") as caught:
        analyze_source('''from pyjs import js
@js
class Value:
    pass
@js
class Holder:
    alias = Value
@js
def main() -> str:
    return str(Holder.alias is Value)
''', filename="class_alias.py", wrap=False, **options)
    assert caught.value.filename == "class_alias.py"
    assert caught.value.lineno == 7


def test_placeholder_class_attribute_uses_the_general_class_value_diagnostic():
    with pytest.raises(CompilationError, match="Class-valued attribute 'hole' is not supported") as caught:
        analyze_source('''from functools import Placeholder
class Holder:
    hole = Placeholder
def main() -> str:
    return str(Holder.hole is Placeholder)
''', filename="marker_alias.py", wrap=False, environment=NATIVE_ENVIRONMENT)
    assert caught.value.filename == "marker_alias.py"
    assert caught.value.lineno == 3


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("expected", ["object", "Callable[[int], int] | object",
                                     "object | Callable[[int], int]"])
@pytest.mark.parametrize("callee", ["named", "local", "parameter"])
def test_callback_arguments_preserve_opaque_union_alternatives(environment, expected, callee):
    options = {"environment": environment} if environment is not None else {}
    extra = f", fn: Callable[[{expected}], int]" if callee == "parameter" else ""
    declaration = f"    fn: Callable[[{expected}], int] = accept\n" if callee == "local" else ""
    target = "accept" if callee == "named" else "fn"
    with analyze_source(f'''from pyjs import js
from collections.abc import Callable
@js
def text(value: str) -> str:
    return value
@js
def accept(value: {expected}) -> int:
    return 42
@js
def main(unused: int{extra}) -> int:
{declaration}    return {target}(text)
''', wrap=False, **options) as analysis:
        assert analysis.entry_point.return_type.name == "int"


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("expected", ["Callable[[int], int]", "Callable[[int], int] | None",
                                     "None | Callable[[int], int]"])
def test_nonopaque_callback_alternatives_still_require_a_compatible_signature(environment, expected):
    options = {"environment": environment} if environment is not None else {}
    with pytest.raises(CompilationError, match="accepts str, but must accept int") as caught:
        analyze_source(f'''from pyjs import js
from collections.abc import Callable
@js
def text(value: str) -> str:
    return value
@js
def main(fn: Callable[[{expected}], int]) -> int:
    return fn(text)
''', filename="opaque_control.py", wrap=False, **options)
    assert caught.value.filename == "opaque_control.py"
    assert caught.value.lineno == 8


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("attribute", ["__eq__(None)", "__ne__(None)", "__name__"])
def test_named_function_runtime_attributes_are_located_diagnostics(environment, attribute):
    options = {"environment": environment} if environment is not None else {}
    with pytest.raises(CompilationError, match="Runtime function attribute .* is not supported") as caught:
        analyze_source(f'''from pyjs import js
@js
def callback(value: int) -> int:
    return value
@js
def main() -> str:
    return str(callback.{attribute})
''', filename="function_attribute.py", wrap=False, **options)
    assert caught.value.filename == "function_attribute.py"
    assert caught.value.lineno == 7
