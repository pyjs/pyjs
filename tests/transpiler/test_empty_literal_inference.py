import ast
from textwrap import dedent

import pytest

from pyjs.analysis.analyzer import analyzed_representation, iterable_protocol
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import CollectionNew, build_program_ir, validate_program_ir
from pyjs.analysis.objects import Dict, GenericClass, List, Tuple
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.numeric import NumericFormat
from pyjs.testing.helpers import aat, assert_module_analysis_transpile
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import (
    EMPTY_LITERAL_SIBLING_CONTRACT,
    ITERABLE_LITERAL_CONTEXT_CONTRACT,
)
from tests.semantics.helpers import assert_semantics, run_javascript


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "llvm", "jvm", "wasm"])
def test_fixed_tuple_iterable_context_has_one_homogeneous_item_witness(environment):
    with analyze_source('''
        from collections.abc import Iterable
        from pyjs import int8, js
        @js
        def consume(values: Iterable[list[int8]]) -> int:
            return 0
        @js
        def main() -> int:
            return consume(([int8(1)], [int8(2)]))
    ''', wrap=False, environment=environment) as analysis:
        literal = next(node for node in ast.walk(analysis.entry_point.node) if isinstance(node, Tuple))
        protocol = iterable_protocol(literal.obj, analyzed_representation(literal))
        assert protocol.item_type.to_annotation_str() == 'list[int]'
        assert protocol.item_representation.item_representation.numeric == NumericFormat('integer', 8, True)
        assert not protocol.representation_conflict


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "llvm", "jvm", "wasm"])
def test_union_numeric_width_diagnostic_locates_the_converted_expression(environment):
    source = ("from pyjs import int8, int16, js\n"
              "@js\n"
              "def receive(value: int8 | None) -> None:\n"
              "    result: int16 | None = value\n"
              "@js\n"
              "def main() -> None:\n"
              "    receive(None)\n")
    with pytest.raises(CompilationError, match="different fixed-width numeric types cannot be assigned implicitly") as caught:
        with analyze_source(source, wrap=False, environment=environment):
            pass
    assert caught.value.diagnostic.primary.span.start_position.line == 3


def test_empty_literal_siblings_have_exact_analyzed_and_javascript_types():
    aat('''
        rows = [[], [1], []]
        records = [{}, {"score": 2}, {}]
        values = {"empty": [], "filled": [3]}
    ''', '''
        rows: list[list[int]] = [[], [1], []]
        records: list[dict[str, int]] = [{}, {'score': 2}, {}]
        values: dict[str, list[int]] = {'empty': [], 'filled': [3]}
    ''', '''
        var rows = [[], [1], []];
        var records = [new Map([]), new Map([['score', 2]]), new Map([])];
        var values = new Map([['empty', []], ['filled', [3]]]);
    ''')


def test_empty_literal_ir_preserves_recursive_representation():
    with analyze_source(dedent('''
        from pyjs import int64

        def main():
            return {"empty": [], "filled": [int64(9007199254740993)]}
    '''), environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        containers = [
            node
            for block in analysis.entry_point.ir.blocks
            for statement in getattr(block, "body", ())
            for node in ast.walk(statement)
            if isinstance(node, CollectionNew)
        ]
        mapping, empty, filled = containers
        assert empty.value_type is filled.value_type
        assert empty.value_type.to_annotation_str() == "list[int]"
        numeric = NumericFormat("integer", 64, True)
        assert analyzed_representation(empty.source).arguments[0].numeric == numeric
        assert analyzed_representation(filled.source) == analyzed_representation(empty.source)
        assert analyzed_representation(mapping.source).arguments[1].arguments[0].numeric == numeric
        assert analysis.entry_point.return_representation == analyzed_representation(mapping.source)
        assert analysis.types == dedent('''
            def main() -> dict[str, list[int]]:
                block entry:
                    return new[caller] dict[str, list[int]]('empty': new[caller] list[int](), 'filled': new[caller] list[int](int(9007199254740993)))
        ''').strip()


@pytest.mark.parametrize("expression", [
    "[[], [int8(1)], [int64(2)]]",
    "{'empty': [], 'small': [int8(1)], 'wide': [int64(2)]}",
])
def test_empty_literal_siblings_do_not_mask_conflicting_representations(expression):
    source = f"from pyjs import int8, int64\ndef main():\n    return {expression}\n"
    with pytest.raises(CompilationError, match="incompatible nested representations"):
        with analyze_source(source, environment=NATIVE_ENVIRONMENT, wrap=False):
            pass


def test_empty_literal_sibling_representations_match_python_in_javascript():
    assert_semantics('''
        from pyjs import int8, int64, js

        @js
        def main() -> None:
            small = [[], [int8(1)]]
            wide = {**{}, "empty": [], "filled": [int64(9007199254740993)]}
            small[0].append(int8(127))
            wide["empty"].append(int64(9007199254740995))
            print(small[0][0] + 1)
            print(wide["empty"][0] + 1)
            print(wide["filled"][0])

        main()
    ''')


def test_shared_empty_literal_sibling_contract():
    assert_semantics(EMPTY_LITERAL_SIBLING_CONTRACT.print_source + "\nmain()")


def test_shared_iterable_literal_context_contract():
    assert_semantics(ITERABLE_LITERAL_CONTEXT_CONTRACT.print_source + "\nmain()")


def test_iterable_nested_literal_has_exact_analysis_and_javascript():
    assert_module_analysis_transpile('''
        from collections.abc import Iterable
        from pyjs import js
        @js
        def consume(values: Iterable[list[list[int]]]) -> None:
            pass
        @js
        def main() -> None:
            consume([[], [[]], [[9]]])
            consume(([], [[]], [[9]]))
    ''', '''
        def consume(values: Iterable__list__list__int) -> None:
            pass

        def main() -> None:
            consume([[], [[]], [[9]]])
            consume(([], [[]], [[9]]))
    ''', '''
        export function consume(values) {
        }

        export function main() {
            consume([[], [[]], [[9]]]);
            consume([[], [[]], [[9]]]);
        }
    ''')


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", [
    "consume([[], [[]], [[int8(127)]]])",
    "consume(values=([], [[]], [[int8(127)]]))",
    "callback([[], [[]], [[int8(127)]]])",
])
def test_iterable_context_retains_nested_empty_numeric_storage(environment, expression):
    with analyze_source(f'''
        from collections.abc import Callable, Iterable
        from pyjs import int8, js
        @js
        def consume(values: Iterable[list[list[int8]]]) -> None:
            pass
        @js
        def main() -> None:
            callback: Callable[[Iterable[list[list[int8]]]], None] = consume
            {expression}
    ''', wrap=False, environment=environment) as analysis:
        literals = [node for node in ast.walk(analysis.entry_point.node) if isinstance(node, List)]
        assert len(literals) in (5, 6)
        for literal in literals:
            representation = analyzed_representation(literal)
            while representation.arguments:
                representation = representation.arguments[0]
            assert representation.numeric == NumericFormat("integer", 8, True)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("annotation, expression", [
    ("list[list[int8]]", expression) for expression in (
        "rows.extend([[], [int8(3)]])", "rows.extend([[int8(3)], []])",
        "rows.extend(([], [int8(3)]))", "rows.extend(([int8(3)], []))", "rows.extend([[], []])",
    )
] + [
    ("list[list[list[int8]]]", "rows.extend([[], [[]], [[int8(3)]]])"),
    ("list[list[list[int8]]]", "rows.extend(([], [[]], [[int8(3)]]))"),
])
def test_receiver_context_retains_empty_sibling_representations(environment, annotation, expression):
    with analyze_source(f'''
        from pyjs import int8, js
        @js
        def main() -> None:
            rows: {annotation} = []
            {expression}
    ''', wrap=False, environment=environment) as analysis:
        literals = [node for node in ast.walk(analysis.entry_point.node) if isinstance(node, List)]
        assert len(literals) >= 3
        for literal in literals:
            representation = analyzed_representation(literal)
            while representation.arguments:
                representation = representation.arguments[0]
            assert representation.numeric == NumericFormat("integer", 8, True)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", ["[[], [int8(3)]]", "([], [int8(3)])"])
def test_receiver_context_does_not_erase_sibling_numeric_storage(environment, expression):
    with pytest.raises(CompilationError, match="incompatible representation"):
        with analyze_source(f'''
            from pyjs import int8, js
            @js
            def main() -> None:
                rows: list[list[int]] = []
                rows.extend({expression})
        ''', wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", [
    "[borrowed, [[int8(3)]]]",
    "[[[]], [[int8(3)]], [[int16(4)]]]",
])
def test_empty_only_descendants_do_not_retype_aliases_or_conflicting_widths(environment, expression):
    with pytest.raises(CompilationError, match="representation"):
        with analyze_source(f'''
            from pyjs import int8, int16, js
            @js
            def main() -> None:
                borrowed: list[list[int]] = [[]]
                rows: list[list[list[int8]]] = []
                rows.extend({expression})
        ''', wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("annotation", ["Iterable[list[int8]]", "list[list[int8]]"])
def test_fresh_populated_siblings_are_normalized_before_representation_merge(environment, annotation):
    with analyze_source(f'''
        from collections.abc import Iterable
        from pyjs import int8, js
        @js
        def consume(rows: {annotation}) -> None:
            pass
        @js
        def main() -> None:
            value = 200
            consume([[], [value]])
            consume([[value], []])
    ''', wrap=False, environment=environment) as analysis:
        literals = [node for node in ast.walk(analysis.entry_point.node) if isinstance(node, List)]
        assert len(literals) == 6
        for literal in literals:
            representation = analyzed_representation(literal)
            while representation.arguments:
                representation = representation.arguments[0]
            assert representation.numeric == NumericFormat("integer", 8, True)


def test_fresh_contextual_storage_converts_slots_not_source_in_javascript():
    result, _ = run_javascript('''
        from collections.abc import Iterable
        from pyjs import int8, js
        @js
        def consume(rows: Iterable[list[int8]]) -> None:
            for row in rows:
                for item in row:
                    print(item + 1)
        @js
        def main() -> None:
            value = 200
            consume([[], [value]])
            consume([[value], []])
            print(value + 1)
    ''')
    # CPython ignores storage annotations; the compiler's explicit slot
    # conversion contract narrows the copies, never the ordinary source.
    assert result.returncode == 0
    assert not result.stderr
    assert result.stdout == '-55\n-55\n201\n'


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", ["[[], borrowed]", "([], borrowed)"])
@pytest.mark.parametrize("item", ["int", "int64"])
def test_iterable_context_does_not_relabel_borrowed_numeric_storage(environment, expression, item):
    with pytest.raises(CompilationError, match="representations|representation"):
        with analyze_source(f'''
            from collections.abc import Iterable
            from pyjs import int8, int64, js
            @js
            def consume(values: Iterable[list[int8]]) -> None:
                pass
            @js
            def main() -> None:
                borrowed: list[{item}] = [{item}(1)]
                consume({expression})
        ''', wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("expression", [
    "[[], []]",
    "[[], [1], ['text']]",
    "[[], StaticArray[int, 1]([1])]",
])
def test_sibling_inference_does_not_guess_missing_ambiguous_or_fixed_storage(expression):
    source = f"from pyjs import StaticArray\ndef main():\n    return {expression}\n"
    with analyze_source(source, wrap=False) as analysis:
        empty = [node for node in ast.walk(analysis.entry_point.node)
                 if isinstance(node, List) and not node.elts]
        assert empty
        assert all(isinstance(node.obj, GenericClass) for node in empty)
        assert all(analyzed_representation(node) is None for node in empty)


def test_mapping_unpack_contributes_sibling_representation_without_changing_aliases():
    assert_semantics('''
        from pyjs import int64, js

        @js
        def main() -> None:
            filled = [int64(9007199254740993)]
            records = {"empty": [], **{"filled": filled}}
            records["empty"].append(int64(9007199254740995))
            records["filled"].append(int64(7))
            print(records["empty"][0] + 1)
            print(filled[1])
            print(filled[0])

        main()
    ''')


@pytest.mark.parametrize("name,literal,node_type", [("list", "[]", List), ("dict", "{}", Dict)])
def test_application_namesakes_do_not_supply_builtin_literal_types(name, literal, node_type):
    source = f"from pyjs import js\n@js\nclass {name}:\n    pass\ndef main():\n    return [{literal}, {name}()]\n"
    with analyze_source(source, wrap=False) as analysis:
        result = analysis.entry_point.node.body[0].value
        empty = result.elts[0]
        assert isinstance(empty, node_type)
        assert isinstance(empty.obj, GenericClass)
        assert analyzed_representation(empty) is None
