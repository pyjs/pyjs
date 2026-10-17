import pytest

from pyjs import int8, int64
from pyjs.analysis.analyzer import JS_ENVIRONMENT
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.representation import annotation_representation
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("expression", ["list(view)", "list(iter(view))", "list(view.__iter__())"])
@pytest.mark.parametrize("key_type,value_type", [(int8, int64), (int64, int8)])
def test_annotated_item_view_keeps_both_representation_fields(environment, expression, key_type, value_type):
    with analyze_source(f'''
        from collections.abc import ItemsView
        from pyjs import int8, int64

        def main(values: dict[{key_type.__name__}, {value_type.__name__}]) -> list[tuple[{key_type.__name__}, {value_type.__name__}]]:
            view: ItemsView[{key_type.__name__}, {value_type.__name__}] = values.items()
            return {expression}
    ''', wrap=False, environment=environment) as analysis:
        assert analysis.entry_point.return_representation == annotation_representation(list[tuple[key_type, value_type]])


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("view,item_type", [("keys", int8), ("values", int64)])
def test_explicit_view_iterator_preserves_its_item_representation(environment, view, item_type):
    with analyze_source(f'''
        from pyjs import int8, int64

        def main(values: dict[int8, int64]) -> list[{item_type.__name__}]:
            return list(values.{view}().__iter__())
    ''', wrap=False, environment=environment) as analysis:
        assert analysis.entry_point.return_representation == annotation_representation(list[item_type])


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("width", ["int8", "int64"])
def test_annotated_item_view_disjoint_checks_the_whole_row(environment, width):
    source = f'''
        from collections.abc import ItemsView
        from pyjs import int8, int64

        def main(view: ItemsView[int8, int8], rows: list[tuple[int8, {width}]]) -> bool:
            return view.isdisjoint(rows)
    '''
    if width == "int8":
        with analyze_source(source, wrap=False, environment=environment):
            pass
    else:
        with pytest.raises(CompilationError, match="representation"):
            with analyze_source(source, wrap=False, environment=environment):
                pass


@pytest.mark.parametrize("environment", [JS_ENVIRONMENT, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("empty", ["[]", "existing"])
def test_empty_comparison_context_types_only_fresh_literals(environment, empty):
    source = f'''
        from pyjs import int8, int64, js

        @js
        def main() -> bool:
            values = {{int8(1)}}
            existing: list[int64] = []
            return values.isdisjoint({empty})
    '''
    if empty == "existing":
        with pytest.raises(CompilationError, match="representation"):
            with analyze_source(source, wrap=False, environment=environment):
                pass
    else:
        with analyze_source(source, wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("retains", ["hash", "equal", "both", "neither"])
def test_view_disjoint_reaches_virtual_callbacks_and_their_retention(retains):
    with analyze_source(f'''
        from collections.abc import KeysView
        from pyjs.native import gc_pin

        class Key:
            def __hash__(self) -> int:
                return 1

            def __eq__(self, other: Key) -> bool:
                return False

            def unrelated(self) -> None:
                pass

        class Child(Key):
            def __hash__(self) -> int:
                {"gc_pin(self)" if retains in {"hash", "both"} else "pass"}
                return 1

            def __eq__(self, other: Key) -> bool:
                {"gc_pin(other)" if retains in {"equal", "both"} else "pass"}
                return False

        def probe(left: KeysView[Key], right: list[Key]) -> bool:
            return left.isdisjoint(right)

        def main() -> bool:
            data: dict[Key, int] = {{Child(): 1}}
            other: list[Key] = [Child()]
            return probe(data.keys(), other)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        module = analysis.entry_point.container
        child = module.search("Child")
        assert {child.find("__eq__"), child.find("__hash__")} <= set(program.functions)
        assert module.search("Key").find("unrelated") not in program.functions
        assert module.search("probe").ir.lifetime.external_parameters == (
            {"left", "right"} if retains != "neither" else set())


@pytest.mark.parametrize("other", ["KeysView", "set", "frozenset"])
@pytest.mark.parametrize("value_type", ["Value", "Child"])
@pytest.mark.parametrize("retains", [False, True])
def test_item_view_disjoint_retains_values_hashed_by_the_other_key_container(other, value_type, retains):
    with analyze_source(f'''
        from collections.abc import ItemsView, KeysView
        from pyjs.native import gc_pin

        class Value:
            def __hash__(self) -> int:
                {"gc_pin(self)" if retains else "pass"}
                return 1

            def __eq__(self, other: Value) -> bool:
                return False

        class Child(Value):
            def __hash__(self) -> int:
                return 2

        def main(left: ItemsView[int, Value], right: {other}[tuple[int, {value_type}]]) -> bool:
            return left.isdisjoint(right)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        assert analysis.entry_point.container.search("Value").find("__hash__") in program.functions
        assert analysis.entry_point.ir.lifetime.external_parameters == (
            {"left", "right"} if retains else set())


@pytest.mark.parametrize("call", [
    "data.keys().isdisjoint([int64(1)])",
    "data.items().isdisjoint([(int8(1), int64(2))])",
    "int64(1) in data.keys()",
    "(int8(1), int64(2)) in data.items()",
])
def test_view_disjoint_does_not_relax_item_representation_contracts(call):
    with pytest.raises(CompilationError, match="representation"):
        with analyze_source(f'''
            from pyjs import int8, int64

            def main() -> bool:
                data = {{int8(1): int8(2)}}
                return {call}
        ''', wrap=False, environment=NATIVE_ENVIRONMENT):
            pass
