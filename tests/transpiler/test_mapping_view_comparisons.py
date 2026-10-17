import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("receiver", ["set[int] | frozenset[int]", "set[int] | None"])
@pytest.mark.parametrize("expression", ["right >= left", "right < left", "right.__le__(left)"])
def test_union_set_receiver_runtime_contracts_do_not_crash_analysis(environment, receiver, expression):
    source = f'''
        def main(left: set[int], right: {receiver}) -> bool:
            return {expression}
    '''
    with analyze_source(source, wrap=False, environment=environment):
        pass
    if environment is NATIVE_ENVIRONMENT:
        # The backend's explicit narrowing boundary is unchanged; shared
        # analysis must not crash before that located diagnostic is emitted.
        with pytest.raises(LLVMUnsupported, match="union.*(narrowed|application).*line"):
            transpile_llvm(source)


@pytest.mark.parametrize("peer", ["set[tuple[int, Value]] | None",
                                  "set[tuple[int, Value]] | frozenset[tuple[int, Value]]"])
@pytest.mark.parametrize("effect", ["hash", "equal", "pure"])
def test_union_view_relation_callbacks_retain_both_operands(peer, effect):
    with analyze_source(f'''
        from collections.abc import ItemsView
        from pyjs.native import gc_pin

        class Value:
            def __hash__(self) -> int:
                {"gc_pin(self)" if effect == "hash" else "pass"}
                return 1

            def __eq__(self, other: Value) -> bool:
                {"gc_pin(self)" if effect == "equal" else "pass"}
                return True

        def main(left: ItemsView[int, Value], right: {peer}) -> bool:
            return left == right
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        assert analysis.entry_point.container.search("Value").find("__hash__") in program.functions
        assert analysis.entry_point.ir.lifetime.external_parameters == ({"left", "right"} if effect != "pure" else set())


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("name", ["KeysView", "ItemsView", "set", "frozenset"])
@pytest.mark.parametrize("operation", ["==", "<="])
def test_application_namesakes_do_not_require_builtin_iteration(environment, name, operation):
    with analyze_source(f'''
        class {name}:
            def __eq__(self, other: {name}) -> bool:
                return True

            def __le__(self, other: {name}) -> bool:
                return True

        def main() -> bool:
            return {name}() {operation} {name}()
    ''', wrap=False, environment=environment):
        pass


@pytest.mark.parametrize("other", ["KeysView", "set", "frozenset"])
@pytest.mark.parametrize("operation", ["==", "!=", "<", "<=", ">", ">="])
@pytest.mark.parametrize("reverse", [False, True])
def test_view_relations_reach_hashes_of_both_operand_types(other, operation, reverse):
    left, right = ("right", "left") if reverse else ("left", "right")
    with analyze_source(f'''
        from collections.abc import ItemsView, KeysView
        from pyjs.native import gc_pin

        class Value:
            def __hash__(self) -> int:
                gc_pin(self)
                return 1

            def __eq__(self, other: Value) -> bool:
                return False

        class Child(Value):
            def __hash__(self) -> int:
                return 1

        def main(left: ItemsView[int, Value], right: {other}[tuple[int, Child]]) -> bool:
            return {left} {operation} {right}
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        assert analysis.entry_point.container.search("Value").find("__hash__") in program.functions
        assert analysis.entry_point.ir.lifetime.external_parameters == {"left", "right"}


@pytest.mark.parametrize("expression", [
    "[left] == [right]", "(left,) == (right,)", "{0: left} == {0: right}",
    "left in [right]", "(0, left) in {0: right}.items()",
    "{0: left}.items().isdisjoint({0: right}.items())",
])
@pytest.mark.parametrize("peer", ["ItemsView[int, Child]", "KeysView[tuple[int, Child]]"])
@pytest.mark.parametrize("effect", ["hash", "equal", "pure"])
def test_nested_view_callbacks_keep_pair_specific_reachability_and_lifetimes(expression, peer, effect):
    source = f'''
        from collections.abc import ItemsView, KeysView
        from pyjs.native import gc_pin

        class Value:
            def __hash__(self) -> int:
                {"gc_pin(self)" if effect == "hash" else "pass"}
                return 1

            def __eq__(self, other: Value) -> bool:
                {"gc_pin(self)" if effect == "equal" else "pass"}
                return True

        class Child(Value):
            def __hash__(self) -> int:
                return 1

        def main(left: ItemsView[int, Value], right: {peer}) -> bool:
            return {expression}
    '''
    if peer.startswith("KeysView") and "isdisjoint" in expression:
        # Unlike equality, isdisjoint's declared iterable argument still
        # requires assignment-compatible items; views are not interchangeable.
        with pytest.raises(CompilationError, match="Argument 'other'.*expects Iterable"):
            with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT):
                pass
        return
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        value = analysis.entry_point.container.search("Value")
        hashes_values = peer.startswith("KeysView")
        assert (value.find("__hash__") in program.functions) == hashes_values
        assert value.find("__eq__") in program.functions
        retains = effect == "equal" or effect == "hash" and hashes_values
        assert analysis.entry_point.ir.lifetime.external_parameters == ({"left", "right"} if retains else set())


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("right", ["ItemsView[int8, WIDTH]", "set[tuple[int8, WIDTH]]"])
@pytest.mark.parametrize("width", ["int8", "int64"])
@pytest.mark.parametrize("expression", ["left == right", "right <= left"])
def test_view_relations_compare_item_representations(environment, right, width, expression):
    source = f'''
        from collections.abc import ItemsView
        from pyjs import int8, int64

        def main(left: ItemsView[int8, int8], right: {right.replace("WIDTH", width)}) -> bool:
            return {expression}
    '''
    if width == "int64":
        with pytest.raises(CompilationError, match="representation"):
            with analyze_source(source, wrap=False, environment=environment):
                pass
    else:
        with analyze_source(source, wrap=False, environment=environment):
            pass
