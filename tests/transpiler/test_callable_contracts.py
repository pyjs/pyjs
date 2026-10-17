import pytest

from pyjs.analysis.diagnostics import CompilationError
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
from pyjs.testing.helpers import analyze_module_source, assert_module_transpile
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.semantics.helpers import assert_semantics


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
        def main() -> int:
            optional = add
            fixed: Callable[[int, int], int] = add
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
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="JS fixed callable views still need optional-argument adapters")
def test_javascript_fixed_callable_view_preserves_supplied_defaults(declaration):
    assert_semantics(f'''
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
