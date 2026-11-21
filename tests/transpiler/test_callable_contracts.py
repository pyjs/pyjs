import pytest

from pyjs.analysis.diagnostics import CompilationError, DiagnosticCode
from pyjs.analysis.objects import (
    specialization_cache_key,
    specialization_type_name,
    union_type_key,
)
from pyjs.analysis.type_relations import (
    merge_conditional_types,
    substitute_type_variables,
)
from pyjs.analysis.value_representation import same_erased_type
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import (
    ad,
    analyze_module_source,
    assert_module_transpile,
    diagnostic_text,
)
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.semantics.helpers import assert_semantics, run_javascript


def test_supplied_callable_defaults_fail_early_on_javascript():
    from tests.backend_semantics import SUPPLIED_CALLABLE_DEFAULT_CONTRACT
    namespace = {}
    exec(SUPPLIED_CALLABLE_DEFAULT_CONTRACT.source, namespace)
    assert namespace["main"]() == 0
    with pytest.raises(CompilationError, match="callable views cannot require optional positional arguments") as caught:
        analyze_module_source(SUPPLIED_CALLABLE_DEFAULT_CONTRACT.source)
    assert caught.value.diagnostic.code == DiagnosticCode.INCOMPATIBLE_ARGUMENT


def test_optional_callable_view_diagnostic_locates_the_source_function():
    ad(
        '''\
        from collections.abc import Callable
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        def main():
            callback: Callable[[int, int], int] = add
        ''',
        diagnostic_text(
            "callback.py", 7, "callback: Callable[[int, int], int] = add",
            "                                      ^^^",
            "pyjs.CompilationError: JavaScript callable views cannot require optional positional arguments [PYJS1104]",
            "help: Call the named function directly or use a fixed-arity wrapper.",
        ),
        filename="callback.py",
    )


def test_native_optional_parameters_keep_their_positional_calling_convention():
    result, _ = run_javascript('''
        from collections.abc import Callable
        from pyjs import js
        @js.native
        class RegExp:
            def __init__(self, pattern: str): ...
            def test(self, value: str = "") -> bool: ...
        @js
        def consume(callback: Callable[[str], bool]) -> bool:
            return callback("abc")
        @js
        def main() -> None:
            print(consume(RegExp("a").test))
    ''')
    assert result.returncode == 0, result.stderr
    assert result.stdout == "True\n"


def test_variadic_function_views_do_not_need_an_options_object():
    assert_semantics('''
        from collections.abc import Callable
        from pyjs import js
        @js
        def total(*values: int) -> int:
            return values[0] + values[1]
        @js
        def consume(callback: Callable[[int, int], int]) -> int:
            return callback(1, 2)
        @js
        def main() -> None:
            print(consume(total))
        main()
    ''')


@pytest.mark.parametrize("parameters,expression", [
    ("value: int, extra: int", "value + extra"),
    ("value: int, *extra: int", "value + extra[0]"),
])
def test_callable_views_use_the_inline_value_implementation_abi(parameters, expression):
    source = f'''
        from collections.abc import Callable
        from pyjs import js
        @js.inline("({{value}} + {{extra}})")
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        @add.value
        def add({parameters}) -> int:
            return {expression}
        @js
        def consume(callback: Callable[[int, int], int]) -> int:
            return callback(1, 2)
        @js
        def main() -> None:
            callback: Callable[[int, int], int] = add
            print(callback(3, 4))
            print(consume(add))
        main()
    '''
    assert_semantics(source)


@pytest.mark.parametrize("default", ["", " = 10"])
def test_callable_views_reject_optional_value_implementations(default):
    with pytest.raises(CompilationError, match="callable views cannot require optional positional arguments"):
        analyze_module_source(f'''
            from collections.abc import Callable
            from pyjs import js
            @js.inline("({{value}} + {{extra}})")
            def add(value: int, extra: int{default}) -> int:
                return value + extra
            @add.value
            def add(value: int, extra: int = 10) -> int:
                return value + extra
            def main() -> int:
                callback: Callable[[int, int], int] = add
                return callback(1, 2)
        ''')


@pytest.mark.parametrize("binding", [
    "callback: Callable[[int, int], int] = add",
    "callback: Callable[[int, int], int] | None = None\ncallback = add",
    "original = add\ncallback: Callable[[int, int], int] = original",
    "callbacks: list[Callable[[int, int], int]] = [add]\ncallback = callbacks[0]",
])
def test_optional_callable_abi_cannot_be_erased_through_storage(binding):
    source = '''from collections.abc import Callable
from pyjs import js
@js
def add(value: int, extra: int = 10) -> int:
    return value + extra
@js
def main() -> int:
'''
    source += "".join("    " + line + "\n" for line in binding.splitlines())
    source += "    return callback(1, 2)\n"
    with pytest.raises(CompilationError, match="callable views cannot require optional positional arguments"):
        analyze_module_source(source)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
@pytest.mark.parametrize("declaration", [
    "callback: Callable[[int], object] = add",
    "callback: Callable[[int], object] | None = None",
])
def test_reassignment_keeps_declared_callable_arity(environment, declaration):
    source = f'''
        from collections.abc import Callable
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        @js
        def main() -> int:
            {declaration}
            callback = add
            return callback(1) + 1
    '''
    with analyze_module_source(source, environment=environment, wrap=False):
        pass
    with pytest.raises(CompilationError, match="Callable expects 1 arguments, got 2"):
        with analyze_module_source(source.replace("callback(1)", "callback(1, 2)"),
                                   environment=environment, wrap=False):
            pass


def test_callable_identity_retains_optional_and_keyword_requirements():
    with analyze_module_source('''
        from collections.abc import Callable
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        @js
        def named(value: int, extra: int = 10, *, label: str) -> int:
            return value + extra
        @js
        def strict(value: int, extra: int) -> int:
            return value + extra
        def main() -> int:
            optional = add
            fixed: Callable[[int, int], int] = strict
            keyword = named
            return optional(1)
    ''') as analysis:
        scope = analysis.entry_point.scope
        optional, fixed, keyword = (scope.lookup(name).cls for name in ("optional", "fixed", "keyword"))
        assert optional.minimum_arguments == 1 and fixed.minimum_arguments == 2
        assert keyword.required_keywords == ("label",)
        for other in (fixed, keyword):
            assert not same_erased_type(optional, other)
            assert union_type_key(optional) != union_type_key(other)
            assert specialization_cache_key(optional) != specialization_cache_key(other)
            assert specialization_type_name(optional) != specialization_type_name(other)
        assert merge_conditional_types(optional, fixed).minimum_arguments == 2
        assert substitute_type_variables(optional, {}).minimum_arguments == 1


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
@pytest.mark.parametrize("use,message", [
    ("wide: Callable[[object], str] = callback", "Cannot assign Callable"),
    ("deferred = lambda: callback('wrong')", "Callable argument 1 expects int, got str"),
])
def test_reassignment_does_not_widen_declared_callable_inputs(environment, use, message):
    source = f'''
        from collections.abc import Callable
        from pyjs import js
        @js
        def broad(value: object) -> str:
            return repr(value)
        @js
        def main() -> None:
            callback: Callable[[int], str] = broad
            callback = broad
            {use}
    '''
    with pytest.raises(CompilationError, match=message):
        with analyze_module_source(source, environment=environment, wrap=False):
            pass


def test_javascript_indirect_optional_argument_boundary_and_direct_positive():
    source = '''
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        def main() -> int:
            callback = add
            return callback(1)
    '''
    assert_module_transpile(source, '''
        export function add(value, { extra=10} = {}) {
            return value + extra;
        }

        export function main() {
            var callback = add;
            return callback(1);
        }
    ''')
    with pytest.raises(CompilationError, match="JavaScript indirect calls cannot supply optional positional arguments"):
        assert_module_transpile(source.replace("callback(1)", "callback(1, 2)"), "")
    assert_semantics('''
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        @js
        def main() -> None:
            callback = add
            print(callback(1), add(1, 2))
        main()
    ''')


def test_structural_mapping_callable_view_uses_iterable_key_conversion():
    # This historical rejection is now supported: Iterable acquisition owns
    # mapping-to-keys conversion, including calls through a returned callback.
    assert_semantics('''
        from collections.abc import Callable, Iterable
        from pyjs import js
        @js
        def consume(values: Iterable[int]) -> int:
            result = 0
            for value in values:
                result += value
            return result
        @js
        def factory() -> Callable[[dict[int, str]], int]:
            return consume
        @js
        def main() -> None:
            print(factory()({1: "one", 3: "three"}), factory()({}))
        main()
    ''')


@pytest.mark.parametrize("arguments", ["*(1, 2)", "*[1, 2]", "*(1, *(2,))", "*pair", "*values"])
def test_javascript_optional_callable_spreads_cannot_bypass_the_boundary(arguments):
    source = f'''
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        def main() -> int:
            pair = (1, 2)
            values = [1, 2]
            callback = add
            return callback({arguments})
    '''
    with pytest.raises(CompilationError, match="JavaScript indirect calls cannot supply optional positional arguments"):
        assert_module_transpile(source, "")


def test_javascript_optional_callable_spreads_preserve_omitted_defaults():
    assert_semantics('''
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        @js
        def main() -> None:
            single = (1,)
            callback = add
            print(callback(*(1,)), callback(*[1]), callback(*single))
        main()
    ''')


@pytest.mark.parametrize("declaration", [
    "callback: Callable[[int, int], int] = add",
    "callback: Callable[[int, int], int] | None = None",
])
def test_javascript_fixed_callable_view_rejects_hidden_optional_arguments(declaration):
    with pytest.raises(CompilationError, match="callable views cannot require optional positional arguments"):
        analyze_module_source(f'''
        from collections.abc import Callable
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        @js
        def main() -> None:
            {declaration}
            callback = add
            print(callback(1, 2))
        main()
        ''')


def test_javascript_fixed_callable_view_default_wrapper():
    assert_semantics('''
        from collections.abc import Callable
        from pyjs import js
        @js
        def add(value: int, extra: int = 10) -> int:
            return value + extra
        @js
        def adapted(value: int, extra: int) -> int:
            return add(value, extra)
        @js
        def main() -> None:
            callback: Callable[[int, int], int] = adapted
            print(callback(1, 2))
        main()
    ''')
