import pytest

from pyjs.testing.helpers import (
    assert_diagnostic,
    assert_module_analysis_transpile,
    diagnostic_text,
)
from tests.backend_semantics import OPTIONAL_INTEGER_CONTRACT
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("backend, optimize", [("javascript", None), ("llvm", 0), ("llvm", 2)])
@pytest.mark.parametrize("container, constructor", [
    ("list[int8]", "[int8(127), int8(2)]"),
    ("StaticArray[int8, 2]", "StaticArray[int8, 2]([int8(127), int8(2)])"),
])
def test_object_storage_keeps_represented_reference_identity(backend, optimize, container, constructor):
    from textwrap import dedent

    # TypedDict storage is a JS surface; native uses the equivalent mapping.
    record_type = "Holder" if backend == "javascript" else "dict[str, object]"
    source = dedent(f'''
        from pyjs import js, int8, StaticArray
        from typing import cast, TypedDict
        class Holder(TypedDict):
            item: object
        @js
        def has_item(items: list[object]) -> bool:
            return len(items) == 1
        @js
        def replace(slot: object, values: {container}) -> bool:
            slot = values
            return slot is values
        @js
        def main() -> int:
            values = {constructor}
            first: object = values
            second: object = 0
            second = values
            optional: object | None = values
            optional_list: list[object] | None = [values]
            listed: list[object] = [values]
            listed = [values]
            paired: tuple[object, object] = (values, values)
            mapped: dict[str, object] = {{"item": values}}
            record: {record_type} = {{"item": values}}
            if first is not values or second is not values or not replace(0, values):
                return 1
            if optional is None or optional is not values:
                return 2
            if optional_list is None or optional_list[0] is not values:
                return 5
            if not has_item(listed) or listed[0] is not values or paired[1] is not values:
                return 3
            if mapped["item"] is not values or record["item"] is not values:
                return 4
            values[0] += int8(1)
            restored = cast({container}, listed[0])
            result = int(restored[0])
            print(result)
            return result
    ''')
    if backend == "javascript":
        assert_semantics(source + "\nmain()\n")
    else:
        from pyjs.tooling.llvm import LLVM
        comparison = LLVM().assert_matches_python(
            source, optimize=optimize, sanitizers=("address", "undefined"),
        )
        assert not comparison.native.stderr


@pytest.mark.parametrize("member", ["values", "[int8(127)]"])
def test_nested_record_object_fields_preserve_represented_reference_storage(member):
    assert_semantics(f'''
from typing import TypedDict, cast
from pyjs import js, int8
class Holder(TypedDict):
    item: object
class Outer(TypedDict):
    holder: Holder
@js
def main() -> None:
    values = [int8(127)]
    record: Outer = {{"holder": {{"item": {member}}}}}
    restored = cast(list[int8], record["holder"]["item"])
    restored[0] += int8(1)
    print(int(restored[0]), restored is values, int(values[0]))
main()
''')


def test_record_object_field_does_not_erase_a_portable_scalar():
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.javascript.source import compile_source

    with pytest.raises(CompilationError, match="incompatible representation"):
        compile_source('''from typing import TypedDict
from pyjs import js, int8
class Holder(TypedDict):
    item: object
@js
def main() -> None:
    record: Holder = {"item": int8(127)}
    print(record)
''')


@pytest.mark.parametrize("backend, optimize", [("javascript", None), ("llvm", 0), ("llvm", 2)])
@pytest.mark.parametrize("same_width", [False, True])
@pytest.mark.parametrize("body", [
    "if flag:\n        slot = [int16(1000)]",
    "for i in range(int(flag)):\n        slot = [int16(1000)]",
    "while flag:\n        slot = [int16(1000)]\n        flag = False",
    "try:\n        if flag:\n            slot = [int16(1000)]\n    finally:\n        pass",
    "if flag:\n        (slot, other) = ([int16(1000)], 0)",
    "entries = [([int16(1000)], 0)]\n    for slot, other in entries[:int(flag)]:\n        pass",
    "try:\n        if flag:\n            slot = [int16(1000)]\n            raise ValueError('changed')\n    except ValueError:\n        pass",
])
def test_erased_reference_flow_keeps_only_compatible_layout(backend, optimize, same_width, body):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.javascript.source import compile_source
    from pyjs.native.llvm import transpile_llvm
    from tests.semantics.helpers import run_python

    if same_width:
        body = body.replace("int16(1000)", "int8(100)")
    source = f'''from pyjs import js, int8, int16
@js
def read(slot: object, flag: bool) -> int:
    slot = [int8(127)]
    {body}
    return int(slot[0] + 1)
@js
def main() -> int:
    print(read(0, True))
    print(read(0, False))
    return 0
'''
    oracle = run_python(source + "\nmain()\n")
    assert oracle.returncode == 0 and oracle.stdout == ("101\n-128\n" if same_width else "1001\n-128\n")
    if same_width:
        if backend == "javascript":
            assert_semantics(source + "\nmain()\n")
        else:
            from pyjs.tooling.llvm import LLVM
            result = LLVM().assert_matches_python(
                source, optimize=optimize, sanitizers=("address", "undefined"),
            )
            assert not result.native.stderr
        return
    compile = compile_source if backend == "javascript" else transpile_llvm
    with pytest.raises(CompilationError) as caught:
        compile(source)
    assert "subscript" in str(caught.value) or "representations" in str(caught.value)
    assert caught.value.diagnostic.primary.span.start_position.line > 0


@pytest.mark.parametrize("backend", ["javascript", "llvm"])
@pytest.mark.parametrize("binding", ["initial", "rebound", "nested"])
@pytest.mark.parametrize("represented_key", [False, True])
def test_mapping_spread_checks_member_representation(backend, binding, represented_key):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.javascript.source import compile_source
    from pyjs.native.llvm import transpile_llvm
    from tests.semantics.helpers import run_python

    annotation = "dict[int, object]" if represented_key else "dict[str, object]"
    initial = "{0: 0}" if represented_key else '{"a": 0}'
    contents = "{int8(100): 0}" if represented_key else '{"a": int8(100)}'
    assignment, mapping = {
        "initial": (f"dest: {annotation} = {{**source}}", "dest"),
        "rebound": (f"dest: {annotation} = {initial}\n    dest = {{**source}}", "dest"),
        "nested": (f"dest: list[{annotation}] = [{{**source}}]", "dest[0]"),
    }[binding]
    item = f"next(iter({mapping}))" if represented_key else f'cast(int, {mapping}["a"])'
    source = f'''from pyjs import js, int8
from typing import cast
@js
def main() -> int:
    source = {contents}
    {assignment}
    print({item} + 100)
    return 0
'''
    oracle = run_python(source + "\nmain()\n")
    assert oracle.returncode == 0 and oracle.stdout == "-56\n"
    compile = compile_source if backend == "javascript" else transpile_llvm
    with pytest.raises(CompilationError, match="Stored mapping items use incompatible representations"):
        compile(source)


def test_mapping_spread_preserves_represented_reference_members():
    source = '''from pyjs import js, int8
from typing import cast
@js
def main() -> int:
    values = [int8(127)]
    source = {"a": values}
    dest: dict[str, object] = {**source}
    dest.update(source)
    restored = cast(list[int8], dest["a"])
    if restored is not values:
        return 1
    values[0] += int8(1)
    print(int(restored[0]))
    return 0
'''
    # Native lowers spread to dict.update; cross-value-type dict.update is a
    # separately tracked capability boundary, not a supported parity case.
    assert_semantics(source + "\nmain()\n")


@pytest.mark.parametrize("backend, optimize", [("javascript", None), ("llvm", 0), ("llvm", 2)])
@pytest.mark.parametrize("declaration", [
    "other: object = values",
    "other: object = None\n    other = values",
    "other: object\n    other = values",
])
@pytest.mark.parametrize("item_type, item", [("int", "100"), ("int8", "int8(100)")])
def test_object_declarations_after_flow_narrowing_keep_storage(
    backend, optimize, declaration, item_type, item,
):
    source = f'''from pyjs import js, int8
from typing import cast
@js
def main() -> int:
    values = [{item}]
    first: object = None
    first = values
    earlier = cast(list[{item_type}], first)
    print(int(earlier[0] + 100))
    {declaration}
    restored = cast(list[{item_type}], other)
    if restored is not values:
        return 1
    print(int(restored[0] + 100))
    optional: object | None = values
    if optional is None:
        return 2
    print(int(cast(list[{item_type}], optional)[0] + 100))
    small: int8 = 100
    small += int8(100)
    print(int(small))
    return 0
'''
    if backend == "javascript":
        assert_semantics(source + "\nmain()\n")
    else:
        from pyjs.tooling.llvm import LLVM
        result = LLVM().assert_matches_python(
            source, optimize=optimize, sanitizers=("address", "undefined"),
        )
        assert not result.native.stderr


@pytest.mark.parametrize("backend, optimize", [("javascript", None), ("llvm", 0), ("llvm", 2)])
@pytest.mark.parametrize("item_type", ["int", "int8"])
@pytest.mark.parametrize("child_scope", [False, True])
def test_child_scope_loop_keeps_declared_storage_on_empty_and_taken_paths(backend, optimize, item_type, child_scope):
    collect = "gc_collect()" if backend == "llvm" else "pass"
    prefix = "first: object = None\n    first = values" if child_scope else "pass"
    # Zero iterations keep an object-typed entry value. Both analyzers must
    # retain that arm; an explicit cast establishes the collection view.
    read = f"cast(list[{item_type}], other)"
    source = f'''from pyjs import js, int8
from typing import cast
from pyjs.native import gc_collect
@js
def check(count: int) -> int:
    values = [{item_type}(127)]
    {prefix}
    other: object = values
    for other in [[{item_type}(125)], [{item_type}(126)]][:count]:
        {collect}
    {collect}
    restored = cast(list[{item_type}], other)
    print(int({read}[0] + 1))
    print(int(restored[0] + 1))
    # Reuse the loop-refined name, including an empty second loop.
    for other in [[{item_type}(100)]][:count]:
        {collect}
    {collect}
    print(int({read}[0] + 1))
    if count == 0 and (restored is not other or restored is not values):
        return 1
    return 0
@js
def main() -> int:
    return check(0) + check(1) + check(2)
'''
    if backend == "javascript":
        assert_semantics(source + "\nmain()\n")
    else:
        from pyjs.tooling.llvm import LLVM
        result = LLVM().assert_matches_python(
            source, optimize=optimize, sanitizers=("address", "undefined"),
        )
        assert not result.native.stderr


@pytest.mark.parametrize("backend", ["javascript", "llvm"])
def test_loop_item_does_not_prove_an_object_entry_is_a_collection(backend):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.javascript.source import compile_source
    from pyjs.native.llvm import transpile_llvm

    compile = compile_source if backend == "javascript" else transpile_llvm
    # The inferred join absorbs the collection arm into object. It still must
    # reject indexing: a loop that runs zero times establishes no collection proof.
    with pytest.raises(CompilationError, match="Value does not have a statically known subscript operation") as caught:
        compile('''from pyjs import js
@js
def main(count: int) -> int:
    value: object = [1]
    for value in [[2]][:count]:
        pass
    return value[0]
''')
    assert caught.value.diagnostic.primary.span.start_position.line == 6


@pytest.mark.parametrize("backend, optimize", [("javascript", None), ("llvm", 0), ("llvm", 2)])
@pytest.mark.parametrize("item_type", ["int", "int8"])
@pytest.mark.parametrize("declared_arm", ["first", "second"])
def test_child_scope_branch_join_uses_one_storage_contract(backend, optimize, item_type, declared_arm):
    first = ": object" if declared_arm == "first" else ""
    second = ": object" if declared_arm == "second" else ""
    collect = "gc_collect()" if backend == "llvm" else "pass"
    source = f'''from pyjs import js, int8
from typing import cast
from pyjs.native import gc_collect
@js
def check(flag: bool) -> int:
    values = [{item_type}(100)]
    first: object = None
    first = values
    if flag:
        other{first} = values
    else:
        other{second} = [{item_type}(1)]
    {collect}
    restored = cast(list[{item_type}], other)
    if flag and restored is not values:
        return 1
    print(int(restored[0] + 100))
    return 0
@js
def main() -> int:
    return check(True) + check(False)
'''
    if backend == "javascript":
        assert_semantics(source + "\nmain()\n")
    else:
        from pyjs.tooling.llvm import LLVM
        result = LLVM().assert_matches_python(
            source, optimize=optimize, sanitizers=("address", "undefined"),
        )
        assert not result.native.stderr


@pytest.mark.parametrize("backend", ["javascript", "llvm", "jvm", "webassembly"])
@pytest.mark.parametrize("binding", ["parameter", "local", "reassignment"])
@pytest.mark.parametrize("annotation, initial, replacement, item", [
    ("int", "0", "int8(100)", "value"),
    ("list[int]", "[0]", "[int8(100)]", "value[0]"),
    ("list[list[int]]", "[[0]]", "[[int8(100)]]", "value[0][0]"),
    ("tuple[int8, int]", "(int8(0), 0)", "(int8(0), int8(100))", "value[1]"),
    ("dict[int8, int]", "{int8(0): 0}", "{int8(0): int8(100)}", "value[int8(0)]"),
    ("Record", "{'a': 0, 'b': 0}", "{'a': int8(0), 'b': int8(100)}", "value['b']"),
])
def test_declared_storage_rejects_implicit_numeric_representation_erasure(
    backend, binding, annotation, initial, replacement, item,
):
    from textwrap import dedent

    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.java import transpile_jvm
    from pyjs.javascript.source import compile_source
    from pyjs.native.llvm import transpile_llvm
    from pyjs.webassembly import transpile_webassembly
    from tests.semantics.helpers import run_python

    parameter = f"value: {annotation}" if binding == "parameter" else ""
    initialization = {
        "parameter": f"value = {replacement}",
        "local": f"value: {annotation} = {replacement}",
        "reassignment": f"value: {annotation} = {initial}\n            value = {replacement}",
    }[binding]
    source = dedent(f'''
        from pyjs import js, int8
        from typing import TypedDict
        class Record(TypedDict):
            a: int8
            b: int
        @js
        def replace({parameter}) -> int:
            {initialization}
            return int({item} + 100)
        @js
        def main() -> int:
            return replace({initial if parameter else ""})
    ''')
    # CPython keeps the int8 object despite the annotation. Erasing its domain
    # would silently change this result from -56 to 200 on compiled backends.
    oracle = run_python(source + "\nprint(main())\n")
    assert oracle.returncode == 0 and oracle.stdout == "-56\n"
    compile = {"javascript": compile_source, "llvm": transpile_llvm,
               "jvm": transpile_jvm, "webassembly": transpile_webassembly}[backend]
    with pytest.raises(CompilationError, match="Stored value uses an incompatible representation") as caught:
        compile(source)
    assert caught.value.diagnostic.primary.span.start_position.line > 0


@pytest.mark.parametrize("backend", ["javascript", "llvm"])
@pytest.mark.parametrize("parameters, argument, empty, populated, item", [
    ("values: list[int8], /", "[int8(1)]", "[]", "[int8(127)]", "values[0]"),
    ("*, values: list[int8]", "values=[int8(1)]", "[]", "[int8(127)]", "values[0]"),
    ("*values: int8", "int8(1)", "()", "(int8(127),)", "values[0]"),
    ("**values: int8", "x=int8(1)", "{}", "{'x': int8(127)}", "values['x']"),
])
def test_annotated_parameter_rebinding_keeps_nested_numeric_representation(
    backend, parameters, argument, empty, populated, item,
):
    source = f'''
        from pyjs import js, int8
        @js
        def replace({parameters}) -> int8:
            values = {empty}
            values = {populated}
            return {item} + int8(1)
        @js
        def main() -> int:
            result = int(replace({argument}))
            print(result)
            return result
    '''
    if backend == "javascript":
        from textwrap import dedent
        assert_semantics(dedent(source) + "\nmain()\n")
    else:
        from pyjs.tooling.llvm import LLVM
        comparison = LLVM().assert_matches_python(source)
        assert not comparison.native.stderr


def test_optional_integer_comparison_and_assignment_contract():
    assert_semantics(OPTIONAL_INTEGER_CONTRACT.print_source + "\nmain()\n")


def test_optional_integer_contract_reaches_webassembly_unsupported_boundary():
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    with pytest.raises(WebAssemblyUnsupported, match="union value storage"):
        transpile_webassembly(OPTIONAL_INTEGER_CONTRACT.source)


@pytest.mark.parametrize("backend", ["javascript", "llvm", "jvm", "webassembly"])
@pytest.mark.parametrize("other", ["float", "float | None", "int8 | None"])
def test_optional_int64_comparisons_validate_all_numeric_members(backend, other):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.java import transpile_jvm
    from pyjs.javascript.source import compile_source
    from pyjs.native.llvm import transpile_llvm
    from pyjs.webassembly import transpile_webassembly

    compile = {"javascript": compile_source, "llvm": transpile_llvm,
               "jvm": transpile_jvm, "webassembly": transpile_webassembly}[backend]
    with pytest.raises(CompilationError, match="cannot be (mixed|compared) implicitly"):
        compile(f'''
            from pyjs import js, int8, int64
            @js
            def compare(value: int64 | None, other: {other}) -> bool:
                return value == other
            def main() -> int:
                return int(compare(None, {"1.0" if other.startswith("float") else "int8(1)"}))
        ''')


@pytest.mark.parametrize("backend", ["javascript", "llvm", "jvm", "webassembly"])
@pytest.mark.parametrize("module, constructor, annotation, diagnostic", [
    ("pyjs", "int8", "int | str", "construction requires a number"),
    ("pyjs", "int8", "int | float", "conversion requires a finite float literal"),
    ("pyjs.shader", "i32", "int | float", "Dynamic Python integers cannot enter WGSL"),
])
def test_fixed_integer_union_constructors_validate_every_member(backend, module, constructor, annotation, diagnostic):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.java import transpile_jvm
    from pyjs.javascript.source import compile_source
    from pyjs.native.llvm import transpile_llvm
    from pyjs.webassembly import transpile_webassembly

    compile = {"javascript": compile_source, "llvm": transpile_llvm,
               "jvm": transpile_jvm, "webassembly": transpile_webassembly}[backend]
    with pytest.raises(CompilationError, match=diagnostic) as caught:
        compile(f"from pyjs import js\nfrom {module} import {constructor}\n@js\ndef convert(value: {annotation}):\n    return {constructor}(value)\n"
                "def main() -> int:\n    return int(convert(3))\n")
    assert caught.value.lineno == 5


def test_float_union_constructor_preserves_portable_result_in_javascript():
    assert_semantics('''
        from pyjs import js, float32

        @js
        def convert(value: int | float) -> float32:
            return float32(value)
        @js
        def main():
            return [float(convert(16777217)), float(convert(1.1))]
    ''')


@pytest.mark.parametrize("backend", ["jvm", "webassembly"])
def test_float_union_constructor_reaches_backend_storage_boundary(backend):
    from pyjs.java import JVMUnsupported, transpile_jvm
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    compile, error = {"jvm": (transpile_jvm, JVMUnsupported),
                      "webassembly": (transpile_webassembly, WebAssemblyUnsupported)}[backend]
    with pytest.raises(error, match="union.*(runtime types|storage)"):
        compile('''from pyjs import float32
def convert(value: int | float) -> float32:
    return float32(value)
def main() -> float32:
    return convert(16777217)
''')


def test_webassembly_union_return_reaches_storage_boundary():
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    with pytest.raises(WebAssemblyUnsupported, match="union value storage"):
        transpile_webassembly('''
def main() -> int | float:
    return 3
''')


@pytest.mark.parametrize("backend", ["javascript", "llvm", "jvm", "webassembly"])
@pytest.mark.parametrize("arguments", ["left=7, right=3", "7, right=3", "right=3, left=7"])
def test_divmod_rejects_keywords_with_located_diagnostics(backend, arguments):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.java import transpile_jvm
    from pyjs.javascript.source import compile_source
    from pyjs.native.llvm import transpile_llvm
    from pyjs.webassembly import transpile_webassembly

    with pytest.raises(TypeError):
        eval(f"divmod({arguments})")
    compile = {"javascript": compile_source, "llvm": transpile_llvm,
               "jvm": transpile_jvm, "webassembly": transpile_webassembly}[backend]
    with pytest.raises(CompilationError, match="positional-only") as caught:
        compile(f"def main() -> int:\n    pair = divmod({arguments})\n    return pair[0]\n")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("backend", ["llvm", "jvm"])
@pytest.mark.parametrize("type_name,value", [("int64", "125"), ("float32", "2.675")])
@pytest.mark.parametrize("number_first", [False, True])
def test_native_keyword_round_preserves_analyzed_representation(backend, type_name, value, number_first):
    import ast

    from pyjs import numeric
    from pyjs.analysis.source import analyze_source
    from pyjs.analysis.value_representation import analyzed_numeric_format
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.native.analysis import NATIVE_ENVIRONMENT
    from pyjs.python import native

    number = f"number={type_name}({value})"
    arguments = f"{number}, ndigits=2" if number_first else f"ndigits=2, {number}"
    source = f"from pyjs import {type_name}\ndef main(): return round({arguments})\n"
    environment = NATIVE_ENVIRONMENT if backend == "llvm" else JVM_ENVIRONMENT
    expected = numeric.numeric_format(getattr(numeric, type_name))
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        function = analysis.entry_point
        assert function.return_numeric_format == expected
        calls = [node for block in function.ir.blocks for statement in getattr(block, "body", ())
                 for node in ast.walk(statement) if isinstance(node, ast.Call)
                 and getattr(getattr(node.func, "obj", None), "py_func", None) is native._round]
        assert len(calls) == 1
        assert analyzed_numeric_format(calls[0]) == expected


def test_property_getters_preserve_represented_results():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        class Box:
            @property
            def value(self) -> int8:
                return int8(127)

        def main() -> None:
            print(Box().value + 1)

        main()
        """
    )


def test_property_setters_reject_incompatible_representations():
    source = """
    from pyjs import int8, int16, js

    @js
    class Box:
        @property
        def value(self) -> int8:
            return int8(0)

        @value.setter
        def value(self, new_value: int8) -> None:
            pass

    @js
    def main() -> None:
        box = Box()
        box.value = int16(1)
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "property_setter.py",
            17,
            "box.value = int16(1)",
            "            ^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="property_setter.py",
    )


@pytest.mark.parametrize(
    "expression",
    (
        "cast(int8, int8(127)) + 1",
        "cast(list[int8], [int8(127)])[0] + 1",
    ),
)
def test_typing_cast_preserves_runtime_representations(expression):
    assert_semantics(
        f"""
        from typing import cast

        from pyjs import int8, js

        @js
        def main() -> None:
            print({expression})

        main()
        """
    )


def test_typing_cast_cannot_claim_an_incompatible_representation():
    source = """
    from typing import cast

    from pyjs import int8, int16, js

    @js
    def main() -> None:
        print(cast(int16, int8(1)))
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "cast.py",
            8,
            "print(cast(int16, int8(1)))",
            "      ^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: typing.cast() cannot change a value's "
            "runtime representation [PYJS1104]",
            "help: Construct the fixed-width or StaticArray value explicitly "
            "before casting it.",
        ),
        filename="cast.py",
    )


def test_overloads_select_same_shape_represented_parameters_and_results():
    assert_semantics(
        """
        from typing import overload

        from pyjs import int8, int16, js

        @overload
        def choose(value: int8) -> int8: ...

        @overload
        def choose(value: int16) -> int16: ...

        @js
        def choose(value: int) -> int:
            return value

        @js
        def main() -> None:
            print(choose(int8(127)) + 1)
            print(choose(int16(32767)) + 1)

        main()
        """
    )


def test_literal_overloads_preserve_represented_results():
    assert_semantics(
        """
        from typing import Literal, overload

        from pyjs import int8, int16, js

        @overload
        def choose(kind: Literal["small"], value: int8) -> int8: ...

        @overload
        def choose(kind: Literal["large"], value: int16) -> int16: ...

        @js
        def choose(kind: str, value: int) -> int:
            return value

        @js
        def main() -> None:
            print(choose("small", int8(127)) + 1)
            print(choose("large", int16(32767)) + 1)

        main()
        """
    )


def test_union_normalization_selects_the_runtime_distinguishable_member():
    assert_module_analysis_transpile(
        """
        from pyjs import int8, js

        @js
        def choose(value: int8 | str) -> int8 | str:
            return value

        @js
        def main() -> None:
            print(choose("x"))
        """,
        """
        def choose(value: int | str) -> int | str:
            return value

        def main() -> None:
            print(choose('x'))
        """,
        """
        export function choose(value) {
            return value;
        }

        export function main() {
            console.log(choose('x'));
        }
        """,
    )


def test_union_normalization_preserves_generic_and_static_array_alternatives():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def choose_list(value: list[int8] | str) -> list[int8] | str:
            return value

        @js
        def choose_array(
            value: StaticArray[int8, 1] | str,
        ) -> StaticArray[int8, 1] | str:
            return value

        @js
        def main() -> None:
            print(choose_list("list"))
            print(choose_array("array"))

        main()
        """
    )


def test_cast_allows_representation_safe_union_widening_and_narrowing():
    assert_semantics(
        """
        from typing import cast

        from pyjs import int8, js

        @js
        def widen(value: int8) -> int8 | None:
            return cast(int8 | None, value)

        @js
        def narrow(value: int8 | None) -> int8:
            return cast(int8, value)

        @js
        def main() -> None:
            print(widen(int8(127)))
            print(narrow(int8(127)) + 1)

        main()
        """
    )


def test_nested_and_redundant_represented_unions_are_canonicalized():
    assert_semantics(
        """
        from typing import Optional, Union

        from pyjs import int8, js

        @js
        def optional(value: Optional[int8 | None]) -> int8 | None:
            return value

        @js
        def nested(
            value: Union[Union[int8, str], None],
        ) -> int8 | str | None:
            return value

        @js
        def main() -> None:
            print(optional(int8(127)))
            print(nested("value"))
            print(nested(None))

        main()
        """
    )


def test_union_normalization_preserves_ordinary_members_at_storage_boundaries():
    assert_semantics(
        """
        from typing import TypedDict

        from pyjs import StaticArray, int8, js

        class Record(TypedDict):
            value: int8 | str

        @js
        class Settings:
            value: int8 | str = "class"

        @js
        def show_default(value: int8 | str = "default") -> None:
            print(value)

        @js
        def collect(
            value: int8 | str,
            *items: int8 | str,
            **fields: int8 | str,
        ) -> None:
            print(value, items[0], fields["field"])

        @js
        def main() -> None:
            value: int8 | str = "local"
            value = "assigned"
            values: list[int8 | str] = ["list"]
            mapping: dict[str, int8 | str] = {"value": "mapping"}
            array = StaticArray[int8 | str, 1](["array"])
            record: Record = {"value": "record"}
            print(value, values[0], mapping["value"])
            print(array[0], record["value"], Settings.value)
            values.append("added")
            mapping["next"] = "mapping-added"
            array[0] = "array-updated"
            record["value"] = "record-updated"
            print(values[1], mapping["next"])
            print(array[0], record["value"])
            collect("argument", "vararg", field="keyword")
            show_default()

        main()
        """
    )


def test_union_normalization_prefers_exact_bool_members_everywhere():
    assert_semantics(
        """
        from typing import TypedDict

        from pyjs import StaticArray, int8, js

        class Row(TypedDict):
            value: bool | int8

        @js
        def main() -> None:
            direct: bool | int8 = True
            values: list[bool | int8] = [True]
            record: Row = {"value": True}
            fixed = StaticArray[bool | int8, 1]([True])
            reversed_union: int8 | bool = True
            reversed_fixed = StaticArray[int8 | bool, 1]([True])
            print("bool" if isinstance(direct, bool) else "int")
            print("bool" if isinstance(values[0], bool) else "int")
            print("bool" if isinstance(record["value"], bool) else "int")
            print("bool" if isinstance(fixed[0], bool) else "int")
            print("bool" if isinstance(reversed_union, bool) else "int")
            print("bool" if isinstance(reversed_fixed[0], bool) else "int")

        main()
        """
    )


def test_cast_projects_a_represented_union_onto_an_ordinary_member():
    assert_semantics(
        """
        from typing import cast

        from pyjs import int8, js

        @js
        def consume(value: str) -> None:
            print(value)

        @js
        def show(value: int8 | str) -> None:
            consume(cast(str, value))

        show("ordinary")
        """
    )


def test_bare_yield_uses_the_yield_expression_for_conflict_diagnostics(
    monkeypatch,
):
    import pyjs.analysis.analyzer

    monkeypatch.setattr(
        pyjs.analysis.analyzer,
        "representations_conflict",
        lambda _values: True,
    )
    assert_diagnostic(
        """\
        from pyjs import js

        @js
        def values():
            yield
        """,
        diagnostic_text(
            "bare_yield.py",
            5,
            "yield",
            "^^^^^",
            "pyjs.CompilationError: Generator yields incompatible value "
            "representations [PYJS1105]",
            "help: Yield one represented type for each result type, or add "
            "an explicit conversion.",
        ),
        filename="bare_yield.py",
    )


@pytest.mark.parametrize(
    ("loop", "line"),
    (
        ("for _item in []:\n            value = int16(1)", "for _item in []:"),
        ("while False:\n            value = int16(1)", "while False:"),
    ),
)
def test_zero_iteration_loops_reject_representation_changes(loop, line):
    source = f"""
    from pyjs import int8, int16, js

    @js
    def main() -> None:
        value = int8(127)
        {loop}
        print(value + 1)
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "loop.py",
            7,
            line,
            "^" * len(line),
            "pyjs.CompilationError: Branches assign incompatible numeric "
            "representations to 'value' [PYJS1103]",
            "help: Use an explicit fixed-width annotation to convert every "
            "branch, or keep every branch as an ordinary Python number.",
        ),
        filename="loop.py",
    )


def test_starred_literal_does_not_imply_a_nonempty_loop():
    line = "for _item in [*items]:"
    assert_diagnostic(
        """\
        from pyjs import int8, int16, js

        @js
        def main() -> None:
            value = int8(1)
            items: list[int] = []
            for _item in [*items]:
                break
            else:
                value = int16(257)
        """,
        diagnostic_text(
            "starred_loop.py",
            7,
            line,
            "^" * len(line),
            "pyjs.CompilationError: Branches assign incompatible numeric "
            "representations to 'value' [PYJS1103]",
            "help: Use an explicit fixed-width annotation to convert every "
            "branch, or keep every branch as an ordinary Python number.",
        ),
        filename="starred_loop.py",
    )


def test_try_handlers_reject_representation_changes():
    source = """
    from pyjs import int8, int16, js

    @js
    def main(fail: bool) -> None:
        value = int8(127)
        try:
            if fail:
                raise ValueError("fail")
            value = int16(1)
        except ValueError:
            value = int8(127)
        print(value + 1)
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "try.py",
            7,
            "try:",
            "^^^^",
            "pyjs.CompilationError: Branches assign incompatible numeric "
            "representations to 'value' [PYJS1103]",
            "help: Use an explicit fixed-width annotation to convert every "
            "branch, or keep every branch as an ordinary Python number.",
        ),
        filename="try.py",
    )


def test_loops_preserve_compatible_representations_across_iterations():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def main() -> None:
            value = int8(120)
            for amount in [4, 4]:
                value = int8(value + amount)
            else:
                value = int8(value + 1)
            count = 0
            while count < 2:
                value = int8(value + 1)
                count += 1
            print(value)

        main()
        """
    )


def test_loop_break_exits_participate_in_representation_merging():
    loop = "for item in [1]:\n            if item:\n                break"
    source = f"""\
    from pyjs import int8, int16, js

    @js
    def main() -> None:
        value = int8(1)
        {loop.rstrip()}
        else:
            value = int16(257)
        print(value + 127)
    """
    line = loop.splitlines()[0]
    assert_diagnostic(
        source,
        diagnostic_text(
            "loop_else.py",
            6,
            line,
            "^" * len(line),
            "pyjs.CompilationError: Branches assign incompatible numeric "
            "representations to 'value' [PYJS1103]",
            "help: Use an explicit fixed-width annotation to convert every "
            "branch, or keep every branch as an ordinary Python number.",
        ),
        filename="loop_else.py",
    )


def test_unconditional_break_makes_while_else_unreachable():
    assert_semantics(
        """
        from pyjs import int8, int16, js

        @js
        def main() -> None:
            value = int8(1)
            while True:
                break
            else:
                value = int16(257)
            print(value + 127)

        main()
        """
    )


def test_loop_continue_and_break_preserve_compatible_representations():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def main() -> None:
            for_value = int8(1)
            for item in [1]:
                for_value = int8(for_value + item)
                continue
            else:
                for_value = int8(for_value + 1)

            while_value = int8(1)
            while True:
                while_value = int8(while_value + 1)
                break
            else:
                while_value = int8(100)

            print(for_value)
            print(while_value)

        main()
        """
    )


@pytest.mark.parametrize(
    ("loop", "underline"),
    (
        ("for _item in [1]:", "^^^^^^^^^^^^^^^^^"),
        ("while True:", "^^^^^^^^^^^"),
    ),
)
def test_break_inside_try_else_participates_in_the_loop_merge(loop, underline):
    source = f"""
    from pyjs import int8, int16, js

    @js
    def main() -> None:
        value = int8(1)
        {loop}
            try:
                pass
            except ValueError:
                pass
            else:
                break
        else:
            value = int16(257)
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "loop_try_else.py",
            7,
            loop,
            underline,
            "pyjs.CompilationError: Branches assign incompatible numeric "
            "representations to 'value' [PYJS1103]",
            "help: Use an explicit fixed-width annotation to convert every "
            "branch, or keep every branch as an ordinary Python number.",
        ),
        filename="loop_try_else.py",
    )


@pytest.mark.parametrize("loop", ("for _item in [1]:", "while True:"))
@pytest.mark.parametrize(
    ("before_break", "in_finally"),
    (
        ("pass", "value = int16(257)"),
        ("value = int16(257)", "value = int8(1)"),
    ),
)
def test_finally_transforms_the_representation_carried_by_break(
    loop,
    before_break,
    in_finally,
):
    assert_semantics(
        f"""
        from pyjs import int8, int16, js

        @js
        def main() -> None:
            value = int8(1)
            {loop}
                try:
                    {before_break}
                    break
                finally:
                    {in_finally}
            print(value + 127)

        main()
        """
    )


def test_loops_reject_changes_to_nested_representations():
    assert_diagnostic(
        """\
        from pyjs import int8, int16, js

        @js
        def main() -> None:
            value = [int8(1)]
            for _item in []:
                value = [int16(1)]
        """,
        diagnostic_text(
            "loop_nested.py",
            6,
            "for _item in []:",
            "^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Branches assign incompatible nested "
            "representations to 'value' [PYJS1103]",
            "help: Use one represented type for each runtime value type, or "
            "add an explicit conversion.",
        ),
        filename="loop_nested.py",
    )


def test_try_else_and_finally_preserve_compatible_representations():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def calculate(fail: bool) -> int8:
            value = int8(120)
            try:
                if fail:
                    raise ValueError("fail")
                value = int8(value + 4)
            except ValueError:
                value = int8(value + 5)
            except Exception:
                value = int8(0)
            else:
                value = int8(value + 1)
            finally:
                value = int8(value + 2)
            return value

        def main() -> None:
            print(calculate(False), calculate(True))

        main()
        """
    )


def test_declared_generator_items_preserve_representations():
    assert_semantics(
        """
        from collections.abc import Iterator

        from pyjs import StaticArray, int8, js

        @js
        def numbers() -> Iterator[int8]:
            yield int8(127)

        @js
        def arrays() -> Iterator[StaticArray[int8, 1]]:
            yield StaticArray[int8, 1]([int8(127)])

        def main() -> None:
            print(next(numbers()) + 1)
            print(next(arrays())[0] + 1)

        main()
        """
    )


def test_declared_generator_items_preserve_compound_representations():
    assert_semantics(
        """
        from collections.abc import Iterator

        from pyjs import int8, js

        @js
        def rows() -> Iterator[list[int8]]:
            yield [int8(127)]

        def main() -> None:
            print(next(rows())[0] + 1)

        main()
        """
    )


def test_declared_generator_items_reject_incompatible_representations():
    assert_diagnostic(
        """\
        from collections.abc import Iterator
        from pyjs import int8, int16, js

        @js
        def numbers() -> Iterator[int8]:
            yield int16(1)
        """,
        diagnostic_text(
            "generator.py",
            6,
            "yield int16(1)",
            "      ^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="generator.py",
    )


def test_represented_class_and_dataclass_defaults_are_supported():
    assert_semantics(
        """
        from dataclasses import dataclass, field, replace

        from pyjs import int8, js

        @js
        def default_limit() -> int8:
            return int8(127)

        @js
        class Settings:
            limit: int8 = int8(127)

        @js
        @dataclass
        class Row:
            value: int8 = int8(127)
            generated: int8 = field(default_factory=default_limit)

        @js
        def main() -> None:
            row = Row()
            changed = replace(row, value=int8(126))
            print(Settings.limit + 1)
            print(row.value + 1, row.generated + 1)
            print(changed.value + 2)

        main()
        """
    )


def test_represented_class_defaults_reject_incompatible_representations():
    assert_diagnostic(
        """\
        from pyjs import int8, int16, js

        @js
        class Settings:
            limit: int8 = int16(1)
        """,
        diagnostic_text(
            "default.py",
            5,
            "limit: int8 = int16(1)",
            "              ^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="default.py",
    )


def test_inherited_represented_field_rejects_an_incompatible_default():
    assert_diagnostic(
        """\
        from pyjs import int8, int16, js

        @js
        class Base:
            value: int8

        @js
        class Child(Base):
            value = int16(1)

        def main() -> None:
            print(Child().value)
        """,
        diagnostic_text(
            "inherited_default.py",
            9,
            "value = int16(1)",
            "        ^^^^^^^^",
            "pyjs.CompilationError: Cannot change the represented storage of "
            "field 'Child.value' in its default value [PYJS1103]",
            "note: inherited_default.py:5:12: Base.value is declared as int8 here",
            "help: Construct the default explicitly with the field's declared type.",
        ),
        filename="inherited_default.py",
    )


def test_inherited_plain_field_rejects_a_represented_default():
    assert_diagnostic(
        """\
        from pyjs import int8, js

        @js
        class Base:
            value: int

        @js
        class Child(Base):
            value = int8(127)

        @js
        def read(value: Base) -> int:
            return value.value + 1

        def main() -> None:
            print(read(Child()))
        """,
        diagnostic_text(
            "plain_inherited_default.py",
            9,
            "value = int8(127)",
            "        ^^^^^^^^^",
            "pyjs.CompilationError: Cannot change the represented storage of "
            "field 'Child.value' in its default value [PYJS1103]",
            "note: plain_inherited_default.py:5:12: Base.value is declared as int here",
            "help: Construct the default explicitly with the field's declared type.",
        ),
        filename="plain_inherited_default.py",
    )


def test_plain_class_field_rejects_a_represented_default():
    assert_diagnostic(
        """\
        from pyjs import int8, js

        @js
        class Settings:
            value: int = int8(127)

        def main() -> None:
            print(Settings.value)
        """,
        diagnostic_text(
            "plain_default.py",
            5,
            "value: int = int8(127)",
            "             ^^^^^^^^^",
            "pyjs.CompilationError: Cannot change the represented storage of "
            "field 'Settings.value' in its default value [PYJS1103]",
            "help: Construct the default explicitly with the field's declared type.",
        ),
        filename="plain_default.py",
    )


def test_dataclass_default_factories_reject_incompatible_representations():
    assert_diagnostic(
        """\
        from dataclasses import dataclass, field
        from pyjs import int8, int16, js

        @js
        def default_limit() -> int16:
            return int16(1)

        @js
        @dataclass
        class Row:
            value: int8 = field(default_factory=default_limit)
        """,
        diagnostic_text(
            "default_factory.py",
            11,
            "value: int8 = field(default_factory=default_limit)",
            "                ^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="default_factory.py",
    )


def test_dataclass_replace_rejects_incompatible_representations():
    assert_diagnostic(
        """\
        from dataclasses import dataclass, replace
        from pyjs import int8, int16, js

        @js
        @dataclass
        class Row:
            value: int8

        @js
        def main() -> None:
            replace(Row(int8(1)), value=int16(1))
        """,
        diagnostic_text(
            "replace.py",
            11,
            "replace(Row(int8(1)), value=int16(1))",
            "                            ^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="replace.py",
    )


def test_finally_can_reconcile_conflicting_try_and_handler_representations():
    assert_semantics(
        """
        from pyjs import int8, int16, js

        @js
        def calculate(fail: bool) -> int8:
            value = int8(1)
            try:
                value = int16(2)
                if fail:
                    raise ValueError("fail")
            except ValueError:
                value = int8(3)
            finally:
                value = int8(value)
            return value

        print(calculate(False), calculate(True))
        """
    )


def test_annotated_static_arrays_work_in_local_and_return_annotations():
    assert_semantics(
        """
        from typing import Annotated

        from pyjs import StaticArray, int8, js

        @js
        def values() -> Annotated[StaticArray[int8, 2], "result"]:
            return StaticArray[int8, 2]([200, 1])

        @js
        def main() -> None:
            data: Annotated[StaticArray[int8, 2], "local"] = values()
            print(data[0] + 127)

        main()
        """
    )


@pytest.mark.parametrize(
    ("body", "expression"),
    (
        (
            "def __add__(self, value: int8) -> int:\n        return value + 127",
            "Box() + int16(1)",
        ),
        (
            "def __radd__(self, value: int8) -> int:\n        return value + 127",
            "int16(1) + Box()",
        ),
        (
            "def __getitem__(self, value: int8) -> int:\n        return value + 127",
            "Box()[int16(1)]",
        ),
        (
            "def __contains__(self, value: int8) -> bool:\n"
            "        return value + 127 > 0",
            "int16(1) in Box()",
        ),
    ),
)
def test_syntax_lowered_dunders_validate_parameter_representations(
    body,
    expression,
):
    body = body.replace("\n", "\n    ")
    source = f"""
    from pyjs import int8, int16, js

    @js
    class Box:
        {body}

    @js
    def main() -> None:
        print({expression})
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "dunder.py",
            11,
            f"print({expression})",
            " " * (6 + expression.index("int16(1)")) + "^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="dunder.py",
    )


@pytest.mark.parametrize(
    ("method", "return_type", "result", "expression"),
    (
        ("__add__", "int", "0", "Box() + int8(1)"),
        ("__add__", "int", "0", "Box().__add__(int8(1))"),
        ("__radd__", "int", "0", "int8(1) + Box()"),
        ("__radd__", "int", "0", "Box().__radd__(int8(1))"),
        ("__getitem__", "int", "0", "Box()[int8(1)]"),
        ("__getitem__", "int", "0", "Box().__getitem__(int8(1))"),
        ("__contains__", "bool", "False", "int8(1) in Box()"),
        ("__contains__", "bool", "False", "Box().__contains__(int8(1))"),
    ),
)
def test_dunder_call_forms_reject_implicit_representation_erasure(
    method,
    return_type,
    result,
    expression,
):
    assert_diagnostic(
        f"""
        from pyjs import int8, js

        @js
        class Box:
            def {method}(self, value: int) -> {return_type}:
                return {result}

        @js
        def main() -> None:
            print({expression})
        """,
        diagnostic_text(
            "dunder_erasure.py",
            11,
            f"print({expression})",
            " " * (6 + expression.index("int8(1)")) + "^^^^^^^",
            "pyjs.CompilationError: Argument uses a represented value where "
            "an ordinary Python value is required [PYJS1104]",
            "help: Convert it to the annotated Python type, or change "
            "the parameter to the represented type.",
        ),
        filename="dunder_erasure.py",
    )


@pytest.mark.parametrize(
    ("method", "expression"),
    (
        ("value", "counter.value(int8(1))"),
        ("__add__", "counter.__add__(int8(1))"),
        ("__add__", "counter + int8(1)"),
    ),
)
def test_application_components_do_not_inherit_builtin_parameter_policy(
    method,
    expression,
):
    assert_diagnostic(
        f"""
        from pyjs import int8, js
        from pyjs.web.domx import CustomElement

        class Counter(CustomElement):
            def {method}(self, item: int) -> int:
                return item + 127

        @js
        def main(counter: Counter) -> int:
            return {expression}
        """,
        diagnostic_text(
            "component_parameter.py",
            11,
            f"return {expression}",
            " " * (7 + expression.index("int8(1)")) + "^^^^^^^",
            "pyjs.CompilationError: Argument uses a represented value where "
            "an ordinary Python value is required [PYJS1104]",
            "help: Convert it to the annotated Python type, or change "
            "the parameter to the represented type.",
        ),
        filename="component_parameter.py",
    )


def test_union_binary_dunder_validates_parameter_representations():
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        class Left:
            def __add__(self, value: int8) -> int:
                return value + 127

        @js
        class Right:
            def __add__(self, value: int8) -> int:
                return value + 127

        @js
        def show(value: Left | Right) -> None:
            print(value + int16(1))
        """,
        diagnostic_text(
            "union_dunder.py",
            17,
            "print(value + int16(1))",
            "              ^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="union_dunder.py",
    )


def test_union_binary_dunders_require_one_representation_contract():
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        class Small:
            def __add__(self, value: int8) -> int8:
                return value

        @js
        class Large:
            def __add__(self, value: int16) -> int16:
                return value

        @js
        def combine(value: Small | Large) -> int:
            return value + int8(1)
        """,
        diagnostic_text(
            "union_dunder.py",
            17,
            "return value + int8(1)",
            "       ^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Operator '+' has incompatible client "
            "lowering across Small|Large and int [PYJS2001]",
            "help: Narrow either operand before applying the operator.",
        ),
        filename="union_dunder.py",
    )


def test_syntax_and_explicit_dunder_calls_match_for_compatible_values():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        class Box:
            def __add__(self, value: int8) -> int8:
                return int8(value + 1)

            def __radd__(self, value: int8) -> int8:
                return int8(value + 2)

            def __getitem__(self, value: int8) -> int8:
                return int8(value + 3)

            def __contains__(self, value: int8) -> bool:
                return value == int8(4)

        box = Box()
        print(box + int8(1), box.__add__(int8(1)))
        print(int8(1) + box, box.__radd__(int8(1)))
        print(box[int8(1)], box.__getitem__(int8(1)))
        print(int8(4) in box, box.__contains__(int8(4)))
        """
    )


def test_static_arrays_preserve_compound_item_representations():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            optional: StaticArray[int8 | None, 2] = [int8(127), None]
            nested: StaticArray[list[int8], 1] = [[int8(127)]]
            value = optional[0]
            if value is not None:
                print(value + 1)
            print(nested[0][0] + 1)

        main()
        """
    )


def test_static_arrays_preserve_all_supported_compound_item_representations():
    assert_semantics(
        """
        from collections.abc import Callable
        from typing import TypedDict

        from pyjs import StaticArray, int8, js

        class Row(TypedDict):
            value: int8

        @js
        def narrow() -> int8:
            return int8(127)

        @js
        def main() -> None:
            tuples: StaticArray[tuple[int8], 1] = [(int8(127),)]
            mappings: StaticArray[dict[str, int8], 1] = [{"value": int8(127)}]
            records: StaticArray[Row, 1] = [{"value": int8(127)}]
            callbacks: StaticArray[Callable[[], int8], 1] = [narrow]
            print(tuples[0][0] + 1)
            print(mappings[0]["value"] + 1)
            print(records[0]["value"] + 1)
            print(callbacks[0]() + 1)

        main()
        """
    )


def test_static_array_constructors_recursively_normalize_compound_items():
    assert_semantics(
        """
        from typing import TypedDict

        from pyjs import StaticArray, int8, js

        class Row(TypedDict):
            value: int8

        @js
        def main() -> None:
            optional = StaticArray[int8 | None, 2]([130, None])
            lists = StaticArray[list[int8], 1]([[130]])
            sets = StaticArray[set[int8], 1]([{130}])
            tuples = StaticArray[tuple[int8], 1]([(130,)])
            mappings = StaticArray[dict[str, int8], 1]([{"value": 130}])
            records = StaticArray[Row, 1]([{"value": 130}])
            optional_value = optional[0]
            if optional_value is not None:
                print(optional_value + 127)
            print(lists[0][0] + 127)
            print(next(iter(sets[0])) + 127)
            print(tuples[0][0] + 127)
            print(mappings[0]["value"] + 127)
            print(records[0]["value"] + 127)

        main()
        """
    )


def test_postponed_typed_dict_fields_keep_nested_representations():
    assert_semantics(
        """
        from __future__ import annotations

        from typing import TypedDict

        from pyjs import StaticArray, int8, js

        class Row(TypedDict):
            value: int8

        @js
        def main() -> None:
            rows = StaticArray[Row, 1]([{"value": 127}])
            print(rows[0]["value"] + 1)

        main()
        """
    )


def test_static_array_unions_resolve_aliased_compound_items():
    assert_semantics(
        """
        from typing import TypedDict

        from pyjs import StaticArray, int8, js

        type Bytes = list[int8]
        type Pair = tuple[int8]

        class Row(TypedDict):
            value: int8

        type Record = Row

        @js
        def main() -> None:
            lists = StaticArray[Bytes | None, 1]([[127]])
            tuples = StaticArray[Pair | None, 1]([(127,)])
            rows = StaticArray[Record | None, 1]([{"value": 127}])
            list_value = lists[0]
            tuple_value = tuples[0]
            row_value = rows[0]
            if list_value is not None:
                print(list_value[0] + 1)
            if tuple_value is not None:
                print(tuple_value[0] + 1)
            if row_value is not None:
                print(row_value["value"] + 1)

        main()
        """
    )


def test_round_preserves_portable_results_and_accepts_int64_ndigits():
    assert_semantics(
        """
        from pyjs import float32, int8, int64, js, uint8

        @js
        def main() -> None:
            print(round(int8(125), -1) + 127)
            print(round(uint8(255), -2))
            print(round(1.25, int64(1)))
            print(round(float32(1.2345), 3))
            print(round(float32(1.2345), 3) + 0.00000001)
            print(round(float32(1.5)))
            print(round(int64(125), -1))
            print(round(int64(125), int64(-1)))
            print(round(int64(135), -1))
            print(round(int64(-125), -1))
            print(round(int64(-135), -1))
            print(round(int64(9_007_199_254_740_993), -1))
            print(round(int64(9_223_372_036_854_775_807), -1))
            print(round(int64(-9_223_372_036_854_775_808), -1))

        main()
        """
    )


def test_divmod_uses_the_ordinary_float_domain_for_mixed_operands():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def main() -> None:
            left_quotient, left_remainder = divmod(300.0, int8(2))
            right_quotient, right_remainder = divmod(int8(-100), 0.5)
            print(left_quotient)
            print(left_remainder)
            print(right_quotient)
            print(right_remainder)

        main()
        """
    )


def test_sum_selects_its_domain_from_fixed_items_and_the_start_value():
    assert_semantics(
        """
        from pyjs import StaticArray, float32, int8, js

        @js
        def main() -> None:
            integers: list[int8] = [int8(100), int8(100)]
            fixed_integers = StaticArray[int8, 2]([100, 100])
            floats = StaticArray[float32, 2]([16777216.0, 1.0])
            print(sum(fixed_integers))
            print(sum(fixed_integers, 0))
            print(sum(fixed_integers, start=0))
            print(sum([int8(100), int8(100)]))
            print(sum(integers, 0.5))
            print(sum(integers, start=0.5))
            print(sum(floats, 0.0) + 1.0)
            print(sum(floats, start=0.0) + 1.0)

        main()
        """
    )


@pytest.mark.parametrize(
    ("annotation", "initializer", "start"),
    (
        ("int8", "[]", ""),
        ("int8", "[int8(1)]", ", 0"),
        ("float32", "[]", ", 16777217.0"),
    ),
)
def test_sum_requires_a_represented_start_for_potentially_empty_iterables(
    annotation,
    initializer,
    start,
):
    source = f"""
    from pyjs import float32, int8, js

    @js
    def main() -> None:
        values: list[{annotation}] = {initializer}
        print(sum(values{start}))
    """
    expression = f"sum(values{start})"
    assert_diagnostic(
        source,
        diagnostic_text(
            "ambiguous_sum.py",
            7,
            f"print({expression})",
            "      " + "^" * len(expression),
            "pyjs.CompilationError: sum() has an ambiguous fixed-width "
            "result for a potentially empty iterable [PYJS1104]",
            "help: Pass a start value using the iterable's fixed-width item "
            "type, or sum a statically non-empty value such as a StaticArray.",
        ),
        filename="ambiguous_sum.py",
    )


def test_sum_accepts_a_represented_start_for_potentially_empty_iterables():
    assert_semantics(
        """
        from pyjs import float32, int8, js

        @js
        def main() -> None:
            integers: list[int8] = []
            floats: list[float32] = []
            print(sum(integers, int8(0)) + 128)
            print(sum(floats, float32(16777217.0)))

        main()
        """
    )


def test_sum_recognizes_nonempty_fixed_tuple_annotations():
    assert_semantics(
        """
        from pyjs import float32, int8, js

        @js
        def byte_total(values: tuple[int8]) -> int8:
            return sum(values)

        @js
        def float_total(
            values: tuple[float32, float32],
        ) -> float32:
            return sum(values)

        @js
        def main() -> None:
            print(byte_total((int8(127),)) + 1)
            print(
                float_total(
                    (float32(16777216.0), float32(1.0)),
                )
            )

        main()
        """
    )


def test_float_domain_converts_int64_values_before_javascript_arithmetic():
    assert_semantics(
        """
        from pyjs import StaticArray, int64, js

        @js
        def main() -> None:
            left = divmod(9.0, int64(2))
            right = divmod(int64(9), 2.0)
            values: list[int64] = [int64(2), int64(3)]
            fixed_values = StaticArray[int64, 2]([2, 3])
            print(left[0])
            print(left[1])
            print(right[0])
            print(right[1])
            print(sum(values, 0.5))
            print(sum(values, start=0.5))
            print(sum(fixed_values, 0.5))
            print(sum(fixed_values, start=0.5))

        main()
        """
    )


@pytest.mark.parametrize(
    ("method", "return_type", "body", "expression"),
    (
        ("__add__", "float", "value + 0.5", "box + int64(2)"),
        ("__radd__", "float", "value + 0.5", "int64(2) + box"),
        ("__getitem__", "float", "value + 0.5", "box[int64(2)]"),
        ("__contains__", "bool", "value > 0.5", "int64(2) in box"),
    ),
)
def test_dunder_call_forms_convert_int64_at_ordinary_float_parameters(
    method,
    return_type,
    body,
    expression,
):
    assert_semantics(
        f"""
        from pyjs import int64, js

        @js
        class Box:
            def {method}(self, value: float) -> {return_type}:
                return {body}

        @js
        def main() -> None:
            box = Box()
            print(box.{method}(int64(2)))
            print({expression})

        main()
        """
    )


def test_lowered_dunder_converts_int64_in_the_analyzed_call():
    assert_module_analysis_transpile(
        """
        from pyjs import int64, js

        @js
        class Box:
            def __add__(self, value: float) -> float:
                return value + 0.5

        @js
        def main() -> float:
            box = Box()
            return box + int64(2)
        """,
        """
        class Box:

            def __add__(value: float) -> float:
                return value.[float]__add__!(0.5)

        def main() -> float:
            box: Box = Box()
            return box.[Box]__add__(float_operand(int(2)))
        """,
        """
        export class Box {

            __add__(value) {
                return value + 0.5;
            }
        }

        export function main() {
            var box = new Box();
            return box.__add__(Number(BigInt.asIntN(64,BigInt('2'))));
        }
        """,
    )


@pytest.mark.parametrize("annotation", ("float32", "float64"))
@pytest.mark.parametrize(
    ("parameter", "body", "argument"),
    (
        ("value", "value", "int64(2)"),
        ("value", "value", "value=int64(2)"),
        ("*values", "values[0]", "int64(2)"),
        ("**values", 'values["item"]', "item=int64(2)"),
    ),
)
def test_float_parameter_conversion_cannot_erase_an_explicit_format(
    annotation,
    parameter,
    body,
    argument,
):
    expression = f"consume({argument})"
    assert_diagnostic(
        f"""
        from pyjs import {annotation}, int64, js

        @js
        def consume({parameter}: {annotation}) -> {annotation}:
            return {body} + 0.5

        @js
        def main() -> {annotation}:
            return {expression}
        """,
        diagnostic_text(
            "float_parameter.py",
            10,
            f"return {expression}",
            " " * (7 + expression.index("int64(2)")) + "^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="float_parameter.py",
    )


@pytest.mark.parametrize(
    ("annotation", "argument"),
    (
        ("int8", "int64(2)"),
        ("float32", "int64(2)"),
        ("float64", "int64(2)"),
        ("list[int8]", "[int64(2)]"),
    ),
)
def test_callable_parameters_validate_declared_representations(
    annotation,
    argument,
):
    assert_diagnostic(
        f"""
        from collections.abc import Callable
        from pyjs import float32, float64, int8, int64, js

        @js
        def main(callback: Callable[[{annotation}], int]) -> int:
            return callback({argument})
        """,
        diagnostic_text(
            "callable_parameter.py",
            7,
            f"return callback({argument})",
            " " * (16 + argument.index("int64(2)")) + "^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="callable_parameter.py",
    )


@pytest.mark.parametrize(
    ("annotation", "argument"),
    (
        ("int", "int64(2)"),
        ("list[int]", "StaticArray[int, 1]([2])"),
    ),
)
def test_callable_parameters_reject_representation_erasure(annotation, argument):
    assert_diagnostic(
        f"""
        from collections.abc import Callable
        from pyjs import StaticArray, int64, js

        @js
        def main(callback: Callable[[{annotation}], int]) -> int:
            return callback({argument})
        """,
        diagnostic_text(
            "callable_parameter.py",
            7,
            f"return callback({argument})",
            " " * 16 + "^" * len(argument),
            "pyjs.CompilationError: Argument uses a represented value where "
            "an ordinary Python value is required [PYJS1104]",
            "help: Convert it to the annotated Python type, or change "
            "the parameter to the represented type.",
        ),
        filename="callable_parameter.py",
    )


def test_callable_parameters_preserve_numeric_conversion_domains():
    assert_semantics(
        """
        from collections.abc import Callable
        from pyjs import float32, int8, int64, js

        @js
        def offset(value: float) -> float:
            return value + 0.5

        @js
        def increment(value: float32) -> float32:
            return value + 1.0

        @js
        def first(values: list[int8]) -> int8:
            return values[0]

        @js
        def invoke(
            ordinary: Callable[[float], float],
            represented: Callable[[float32], float32],
            compound: Callable[[list[int8]], int8],
        ) -> None:
            print(ordinary(int64(2)))
            print(represented(float32(16777216.0)))
            print(compound([int8(127)]) + 1)

        @js
        def main() -> None:
            invoke(offset, increment, first)

        main()
        """
    )


def test_generic_lambda_keeps_its_inferred_representation_in_the_body():
    assert_module_analysis_transpile(
        """
        from collections.abc import Callable
        from pyjs import int8, js

        @js
        def transform[T, R](callback: Callable[[T], R], value: T) -> R:
            return callback(value)

        @js
        def main() -> int8:
            return transform(lambda value: value + 1, int8(127))
        """,
        """
        def transform(callback: Callable[[T], R], value: T) -> R:
            return callback(value)

        def main() -> int:
            return transform(lambda value: normalize_int8(value.[int]__add__!(1)), int(127))
        """,
        """
        export function transform(callback, value) {
            return callback(value);
        }

        export function main() {
            return transform((value) => ((value + 1 << 24) >> 24), ((127 << 24) >> 24));
        }
        """,
    )


def test_float_kwargs_convert_int64_values_at_the_declared_boundary():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def total(**values: float) -> float:
            return values["value"] + 0.5

        @js
        def main() -> None:
            print(total(value=int64(2)))

        main()
        """
    )


def test_float_sum_converts_int64_items_from_union_typed_iterables():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def sequence_total(
            values: list[int64] | tuple[int64, ...],
        ) -> float:
            return sum(values, 0.5)

        @js
        def set_total(values: list[int64] | set[int64]) -> float:
            return sum(values, 0.5)

        @js
        def main() -> None:
            print(sequence_total([int64(2), int64(3)]))
            print(sequence_total((int64(2), int64(3))))
            print(set_total([int64(2), int64(3)]))
            print(set_total({int64(2), int64(3)}))

        main()
        """
    )


def test_int64_start_resolves_union_typed_iterables():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def total(
            values: list[int64] | tuple[int64, ...],
        ) -> int64:
            return sum(values, int64(0))

        @js
        def main() -> None:
            print(total([]))
            print(total([int64(9223372036854775807), int64(1)]))
            print(total((int64(2), int64(3))))

        main()
        """
    )


def test_union_iteration_preserves_a_shared_item_representation():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def total(
            values: list[int8] | tuple[int8, ...],
        ) -> int8:
            result = int8(0)
            for value in values:
                result += value
            return result

        @js
        def main() -> None:
            print(total([int8(100), int8(100)]))
            print(total((int8(127), int8(1))))

        main()
        """
    )


def test_int64_union_sum_without_a_start_has_a_located_diagnostic():
    source = """
    from pyjs import int64, js

    @js
    def total(
        values: list[int64] | tuple[int64, ...],
    ) -> int64:
        return sum(values)
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "union_sum.py",
            5,
            "return sum(values)",
            "       ^^^^^^^^^^^",
            "pyjs.CompilationError: sum() has an ambiguous fixed-width result "
            "for a potentially empty iterable [PYJS1104]",
            "help: Pass a start value using the iterable's fixed-width item "
            "type, or sum a statically non-empty value such as a StaticArray.",
        ),
        filename="union_sum.py",
    )


def test_float_sum_converts_possible_int64_union_items():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def sequence_total(
            values: list[int64] | tuple[float, ...],
        ) -> float:
            return sum(values, 0.5)

        @js
        def set_total(
            values: set[int64] | tuple[float, ...],
        ) -> float:
            return sum(values, 0.5)

        @js
        def main() -> None:
            print(sequence_total([int64(2), int64(3)]))
            print(sequence_total((2.0, 3.0)))
            print(set_total({int64(2), int64(3)}))
            print(set_total((2.0, 3.0)))

        main()
        """
    )


def test_sum_considers_mapping_keys_without_their_represented_values():
    assert_semantics(
        """
        from pyjs import float32, int8, js

        @js
        def total(values: dict[int8, float32]) -> int8:
            return sum(values, int8(0))

        @js
        def main() -> None:
            values = {int8(1): float32(16777216.0)}
            print(total(values) + 127)

        main()
        """
    )


@pytest.mark.parametrize(
    "annotation",
    (
        "list[int64] | tuple[float32, ...]",
        "set[int64] | tuple[float32, ...]",
        "list[int] | tuple[float32, ...]",
        "set[int] | tuple[float32, ...]",
    ),
)
def test_sum_rejects_union_branches_with_ambiguous_float_width(annotation):
    source = f"""
    from pyjs import float32, int64, js

    @js
    def total(values: {annotation}) -> float:
        return sum(values, 0.5)
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "ambiguous_union_sum.py",
            5,
            "return sum(values, 0.5)",
            "       ^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: sum() has an ambiguous numeric result "
            "across iterable branches [PYJS1104]",
            "help: Convert every branch to one item type. A represented float "
            "start can absorb ordinary numeric branches; an ordinary float "
            "start can absorb fixed-width integer branches.",
        ),
        filename="ambiguous_union_sum.py",
    )


def test_float_divmod_converts_possible_int64_union_operands():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def left(value: int64 | float) -> tuple[float, float]:
            return divmod(value, 2.0)

        @js
        def right(value: int64 | float) -> tuple[float, float]:
            return divmod(9.0, value)

        @js
        def main() -> None:
            left_int = left(int64(9))
            left_float = left(9.0)
            right_int = right(int64(2))
            right_float = right(2.0)
            print(left_int[0] == 4.0 and left_int[1] == 1.0)
            print(left_float[0] == 4.0 and left_float[1] == 1.0)
            print(right_int[0] == 4.0 and right_int[1] == 1.0)
            print(right_float[0] == 4.0 and right_float[1] == 1.0)

        main()
        """
    )


def test_sum_uses_custom_iterable_item_representations():
    assert_semantics(
        """
        from collections.abc import Iterator

        from pyjs import int64, js

        @js
        class Values:
            def __iter__(self) -> Iterator[int64]:
                return iter([int64(2), int64(3)])

        @js
        def main() -> None:
            print(sum(Values(), 0.5))

        main()
        """
    )


def test_sum_rejects_ambiguous_custom_iterable_items():
    assert_diagnostic(
        """
        from collections.abc import Iterator

        from pyjs import float32, int64, js

        @js
        class Values:
            def __iter__(self) -> Iterator[int64 | float32]:
                return iter([int64(2)])

        @js
        def total(values: Values) -> float:
            return sum(values, 0.5)
        """,
        diagnostic_text(
            "custom_iterable_sum.py",
            12,
            "return sum(values, 0.5)",
            "       ^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: sum() has an ambiguous numeric result "
            "across iterable branches [PYJS1104]",
            "help: Convert every branch to one item type. A represented float "
            "start can absorb ordinary numeric branches; an ordinary float "
            "start can absorb fixed-width integer branches.",
        ),
        filename="custom_iterable_sum.py",
    )


def test_represented_sum_start_resolves_mixed_container_branches():
    assert_semantics(
        """
        from pyjs import float32, js

        @js
        def total(
            values: list[float32] | tuple[int, ...],
        ) -> float32:
            return sum(values, float32(0.0))

        @js
        def main() -> None:
            print(total([float32(16777216.0), float32(1.0)]))
            print(total((16777216, 1)))

        main()
        """
    )


def test_sum_defers_iterable_representation_conflicts_to_its_result_domain():
    assert_semantics(
        """
        from pyjs import float32, int64, js

        @js
        def integer_total(
            values: list[int64] | tuple[int, ...],
        ) -> float:
            return sum(values, 0.5)

        @js
        def float_total(values: tuple[float32, float]) -> float32:
            return sum(values, float32(0.0))

        @js
        def main() -> None:
            print(integer_total([int64(2), int64(3)]))
            print(integer_total((2, 3)))
            print(float_total((float32(16777216.0), 1.0)))

        main()
        """
    )


def test_represented_sum_start_governs_ordinary_items():
    assert_semantics(
        """
        from pyjs import StaticArray, float32, int8, js

        @js
        def tuple_total(values: tuple[float, float]) -> float:
            return sum(values, int8(0))

        @js
        def single_tuple_total(values: tuple[float]) -> float:
            return sum(values, int8(0))

        @js
        def main() -> None:
            print(sum([127, 1], int8(0)))
            print(sum([16777216, 1], float32(0.0)))
            print(sum([1.25, 0.5], int8(0)))
            print(sum([1, 0.5], int8(0)))
            print(sum((1, 0.5), int8(0)))
            print(tuple_total((1.25, 0.5)))
            print(single_tuple_total((1.25,)))
            print(sum({0.5: "value"}, int8(0)))
            print(sum({1: "one", 0.5: "half"}, int8(0)))
            print(sum(StaticArray[float, 2]([1.25, 0.5]), int8(0)))

        main()
        """
    )


def test_integer_sum_start_rejects_potentially_empty_float_iterables():
    assert_diagnostic(
        """
        from pyjs import int8, js

        @js
        def total(values: list[float]):
            return sum(values, int8(0))
        """,
        diagnostic_text(
            "empty_float_sum.py",
            5,
            "return sum(values, int8(0))",
            "       ^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: sum() has an ambiguous numeric result "
            "across iterable branches [PYJS1104]",
            "help: Convert every branch to one item type. A represented float "
            "start can absorb ordinary numeric branches; an ordinary float "
            "start can absorb fixed-width integer branches.",
        ),
        filename="empty_float_sum.py",
    )


def test_fixed_and_variadic_tuple_annotations_have_distinct_shapes():
    assert_diagnostic(
        """
        from pyjs import js

        @js
        def first(values: tuple[float]) -> float:
            return values[0]

        @js
        def main() -> None:
            print(first((1.0, 2.0)))
        """,
        diagnostic_text(
            "tuple_shape.py",
            10,
            "print(first((1.0, 2.0)))",
            "            ^^^^^^^^^^",
            "pyjs.CompilationError: Argument 'values' to first expects "
            "tuple[float], got tuple[float, float] [PYJS1104]",
            "help: Pass a value compatible with tuple[float].",
        ),
        filename="tuple_shape.py",
    )
    assert_semantics(
        """
        from pyjs import js

        @js
        def length(values: tuple[float, ...]) -> int:
            return len(values)

        @js
        def main() -> None:
            print(length(()))
            print(length((1.0, 2.0)))

        main()
        """
    )


@pytest.mark.parametrize(
    ("filename", "signature", "body", "actual"),
    (
        (
            "variadic_fixed_return.py",
            "def wrong(values: tuple[int, ...]) -> tuple[int]:",
            "return values",
            "tuple[int, ...]",
        ),
        (
            "repeated_fixed_return.py",
            "def wrong() -> tuple[int]:",
            "return (1,) * 2",
            "tuple[int, int]",
        ),
    ),
)
def test_tuple_shape_mismatches_receive_return_diagnostics(
    filename,
    signature,
    body,
    actual,
):
    source = f"""
    from pyjs import js

    @js
    {signature}
        {body}
    """
    expected = signature.rsplit(" -> ", 1)[1][:-1]
    assert_diagnostic(
        source,
        diagnostic_text(
            filename,
            4,
            signature,
            " " * (signature.index(" -> ") + 4) + "^" * len(expected),
            f"pyjs.CompilationError: Function returns {actual}, not "
            f"{expected} [PYJS1105]",
            "help: Change the return annotation or return values so their "
            "types match.",
        ),
        filename=filename,
    )


def test_tuple_repetition_and_variadic_slicing_preserve_shapes():
    assert_semantics(
        """
        from pyjs import js

        @js
        def pair() -> tuple[int, int]:
            return (1,) * 2

        @js
        def reflected_pair() -> tuple[int, int]:
            return 2 * (1,)

        @js
        def empty() -> tuple[int, ...]:
            return (1,) * 0

        @js
        def dynamically_empty(count: int) -> tuple[int, ...]:
            return ((1,) * 0) * count

        @js
        def explicit_pair() -> tuple[int, int]:
            return (1,).__mul__(2)

        @js
        def true_pair() -> tuple[int]:
            return (1,) * True

        @js
        def false_pair() -> tuple[int, ...]:
            return (1,) * False

        @js
        def repeated(values: tuple[int], count: int) -> tuple[int, ...]:
            return values * count

        @js
        def explicitly_repeated(
            values: tuple[int],
            count: int,
        ) -> tuple[int, ...]:
            return values.__mul__(count)

        @js
        def tail(values: tuple[int, ...]) -> tuple[int, ...]:
            return values[1:]

        @js
        def drop_two(values: tuple[int, ...]) -> tuple[int, ...]:
            return values[2:]

        @js
        def main() -> None:
            direct = pair()
            reflected = reflected_pair()
            explicit = explicit_pair()
            true_values = true_pair()
            false_values = false_pair()
            empty_values = empty()
            dynamic_empty = dynamically_empty(10)
            dynamic = repeated((3,), 3)
            explicit_dynamic = explicitly_repeated((4,), 3)
            sliced = tail((1, 2, 3))
            dropped = drop_two((1, 2, 3))
            print(len(direct), direct[0], direct[1])
            print(len(reflected), reflected[0], reflected[1])
            print(len(explicit), explicit[0], explicit[1])
            print(len(true_values), true_values[0])
            print(len(false_values))
            print(len(empty_values))
            print(len(dynamic_empty))
            print(len(dynamic), dynamic[0], dynamic[2])
            print(len(explicit_dynamic), explicit_dynamic[0], explicit_dynamic[2])
            print(len(sliced), sliced[0], sliced[1])
            print(len(dropped), dropped[0])

        main()
        """
    )


@pytest.mark.parametrize("method", ("__mul__", "__rmul__"))
def test_tuple_repetition_dunders_reject_keyword_operands(method):
    source = f"""
    from pyjs import js

    @js
    def main() -> tuple[int, int]:
        return (1,).{method}(times=2)
    """
    line = f"return (1,).{method}(times=2)"
    assert_diagnostic(
        source,
        diagnostic_text(
            "tuple_repeat_keyword.py",
            6,
            line,
            " " * line.index("times") + "^^^^^^^",
            f"pyjs.CompilationError: {method}() parameter 'times' is "
            "positional-only [PYJS1104]",
            "help: Pass 'times' as a positional argument.",
        ),
        filename="tuple_repeat_keyword.py",
    )


def test_unbound_sequence_repetition_uses_bound_semantics():
    assert_semantics(
        """
        from pyjs import js

        @js
        def tuple_values() -> tuple[int, int]:
            return tuple.__mul__((1,), 2)

        @js
        def reflected_tuple_values() -> tuple[int, int]:
            return tuple.__rmul__((1,), 2)

        @js
        def list_values() -> list[int]:
            return list.__mul__([1], 2)

        @js
        def reflected_list_values() -> list[int]:
            return list.__rmul__([1], 2)

        @js
        def main() -> None:
            first = tuple_values()
            second = reflected_tuple_values()
            third = list_values()
            fourth = reflected_list_values()
            print(len(first), first[0], first[1])
            print(len(second), second[0], second[1])
            print(len(third), third[0], third[1])
            print(len(fourth), fourth[0], fourth[1])

        main()
        """
    )


def test_unbound_tuple_repetition_rewrites_to_the_bound_operation():
    assert_module_analysis_transpile(
        """
        from pyjs import js

        @js
        def main() -> tuple[int, int]:
            return tuple.__mul__((1,), 2)
        """,
        """
        def main() -> tuple[int, int]:
            return (1,).[tuple__int]__mul__!(2)
        """,
        """
        export function main() {
            return ((values,times)=>{const result=[];for(let index=0;index<times;index++)result.push(...values);return result;})([1],2);
        }
        """,
        filename="unbound_tuple.py",
    )


@pytest.mark.parametrize(
    ("collection", "value", "method"),
    (
        ("tuple", "(1,)", "__mul__"),
        ("tuple", "(1,)", "__rmul__"),
        ("list", "[1]", "__mul__"),
        ("list", "[1]", "__rmul__"),
    ),
)
def test_unbound_sequence_repetition_rejects_keyword_operands(
    collection,
    value,
    method,
):
    source = f"""
    from pyjs import js

    @js
    def main():
        return {collection}.{method}({value}, times=2)
    """
    line = f"return {collection}.{method}({value}, times=2)"
    assert_diagnostic(
        source,
        diagnostic_text(
            "unbound_repeat_keyword.py",
            6,
            line,
            " " * line.index("times") + "^^^^^^^",
            f"pyjs.CompilationError: {method}() parameter 'times' is "
            "positional-only [PYJS1104]",
            "help: Pass 'times' as a positional argument.",
        ),
        filename="unbound_repeat_keyword.py",
    )


def test_unbound_sequence_repetition_requires_a_receiver():
    source = """
    from pyjs import js

    @js
    def main():
        return tuple.__mul__()
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "missing_receiver.py",
            6,
            "return tuple.__mul__()",
            "       ^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: tuple.__mul__() requires a positional "
            "receiver [PYJS1104]",
            "help: Pass the tuple value as the first argument.",
        ),
        filename="missing_receiver.py",
    )


def test_unbound_sequence_repetition_rejects_an_incorrect_receiver():
    source = """
    from pyjs import js

    @js
    def main():
        return tuple.__mul__([1], 2)
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "wrong_receiver.py",
            6,
            "return tuple.__mul__([1], 2)",
            "                     ^^^",
            "pyjs.CompilationError: tuple.__mul__() requires a tuple receiver "
            "[PYJS1104]",
            "help: Pass a tuple value as the first argument.",
        ),
        filename="wrong_receiver.py",
    )


@pytest.mark.parametrize(
    "expression",
    (
        "list.__name__",
        "dict.__name__",
        "tuple.__len__",
        "StaticArray.__name__",
    ),
)
def test_unspecialized_generic_type_attributes_have_a_located_diagnostic(
    expression,
):
    source = f"""
    from pyjs import StaticArray, js

    @js
    def main() -> None:
        print({expression})
    """
    line = f"print({expression})"
    assert_diagnostic(
        source,
        diagnostic_text(
            "generic_attribute.py",
            6,
            line,
            "      " + "^" * len(expression),
            "pyjs.CompilationError: Runtime access to unspecialized generic "
            "type attributes is not supported [PYJS2001]",
            "help: Access the attribute through a concrete value instead.",
        ),
        filename="generic_attribute.py",
    )


@pytest.mark.parametrize(
    ("expression", "marked"),
    (
        ("value = list[int]", "list[int]"),
        ("value = StaticArray[int8, 2]", "StaticArray[int8, 2]"),
        (
            "print(StaticArray[int8, 2].__name__)",
            "StaticArray[int8, 2]",
        ),
    ),
)
def test_specialized_generic_values_have_a_located_diagnostic(
    expression,
    marked,
):
    source = f"""
    from pyjs import StaticArray, int8, js

    @js
    def main() -> None:
        {expression}
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "specialized_generic.py",
            6,
            expression,
            " " * expression.index(marked) + "^" * len(marked),
            "pyjs.CompilationError: Runtime use of specialized generic "
            "types is not supported [PYJS2001]",
            "help: Use specialized generic types in annotations or call "
            "them directly as constructors.",
        ),
        filename="specialized_generic.py",
    )


@pytest.mark.parametrize(
    "annotation",
    (
        "list[int] | tuple[int, ...]",
        "list[int8] | tuple[int8, ...]",
    ),
)
def test_union_container_indexing_has_a_located_diagnostic(annotation):
    source = f"""
    from pyjs import int8, js

    @js
    def first(values: {annotation}):
        return values[0]
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "union_index.py",
            5,
            "return values[0]",
            "       ^^^^^^",
            "pyjs.CompilationError: Subscript access on union values is not "
            "supported [PYJS2001]",
            "help: Narrow the value with isinstance() before indexing it.",
        ),
        filename="union_index.py",
    )


@pytest.mark.parametrize(
    ("statement", "marked"),
    (
        ("print(values.__getitem__(0))", "values"),
        ("values[0] = 1", "values"),
        ("values[0:1] = [1]", "values"),
        ("del values[0]", "values"),
        ("del values[0:1]", "values"),
        ("values.__setitem__(0, 1)", "values"),
        ("values.__delitem__(0)", "values"),
    ),
)
def test_union_container_operations_require_narrowing(statement, marked):
    source = f"""
    from pyjs import js

    @js
    def change(values: list[int] | list[str]) -> None:
        {statement}
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "union_mutation.py",
            5,
            statement,
            " " * statement.index(marked) + "^" * len(marked),
            "pyjs.CompilationError: Subscript access on union values is not "
            "supported [PYJS2001]",
            "help: Narrow the value with isinstance() before indexing it.",
        ),
        filename="union_mutation.py",
    )


@pytest.mark.parametrize(
    "annotation",
    (
        "list[int]",
        "list[int] | list[str]",
    ),
)
@pytest.mark.parametrize(
    "statement",
    (
        "values[0]: int",
        "values[0]: int = 1",
    ),
)
def test_annotated_subscript_assignments_have_a_located_diagnostic(
    annotation,
    statement,
):
    source = f"""
    from pyjs import js

    @js
    def change(values: {annotation}) -> None:
        {statement}
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "annotated_subscript.py",
            5,
            statement,
            "^^^^^^^^^",
            "pyjs.CompilationError: Annotated subscript assignments are not "
            "supported [PYJS2001]",
            "help: Annotate the container's item type and use a normal "
            "subscript assignment.",
        ),
        filename="annotated_subscript.py",
    )


def test_narrowed_union_containers_allow_item_mutation():
    assert_semantics(
        """
        from pyjs import js

        @js
        def clear(values: list[int] | dict[int, int]) -> None:
            if isinstance(values, list):
                values[0] = 2
                del values[0]
            else:
                values[0] = 2
                del values[0]

        @js
        def main() -> None:
            items = [1]
            mapping = {0: 1}
            clear(items)
            clear(mapping)
            print(len(items), len(mapping))

        main()
        """
    )


def test_large_literal_tuple_repetition_uses_bounded_variadic_metadata():
    assert_module_analysis_transpile(
        """
        from pyjs import js

        @js
        def main() -> int:
            values = (1,) * 100_000_000
            return len(values)
        """,
        """
        def main() -> int:
            values: tuple[int, ...] = (1,).[tuple__int]__mul__!(100000000)
            return values.[tuple__int__variadic]__len__!()
        """,
        """
        export function main() {
            var values = ((values,times)=>{const result=[];for(let index=0;index<times;index++)result.push(...values);return result;})([1],100000000);
            return values.length;
        }
        """,
        filename="large_tuple.py",
    )


def test_boolean_tuple_repetition_preserves_exact_shapes():
    assert_module_analysis_transpile(
        """
        from pyjs import js

        @js
        def main() -> int:
            true_values = (1,) * True
            false_values = (1,) * False
            return len(true_values) + len(false_values)
        """,
        """
        def main() -> int:
            true_values: tuple[int] = (1,).[tuple__int]__mul__!(True)
            false_values: tuple__ = (1,).[tuple__int]__mul__!(False)
            return true_values.[tuple__int]__len__!().[int]__add__!(false_values.[tuple__]__len__!())
        """,
        """
        export function main() {
            var true_values = ((values,times)=>{const result=[];for(let index=0;index<times;index++)result.push(...values);return result;})([1],true);
            var false_values = ((values,times)=>{const result=[];for(let index=0;index<times;index++)result.push(...values);return result;})([1],false);
            return true_values.length + false_values.length;
        }
        """,
        filename="boolean_tuple.py",
    )


@pytest.mark.parametrize(
    ("numeric", "annotation"),
    (
        ("int8", "list[int8] | tuple[float, ...]"),
        ("int64", "list[int64] | tuple[float, ...]"),
    ),
)
def test_integer_sum_start_cannot_resolve_ordinary_float_branches(
    numeric,
    annotation,
):
    source = f"""
    from pyjs import {numeric}, js

    @js
    def total(values: {annotation}):
        return sum(values, {numeric}(0))
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "integer_start_float_branch.py",
            5,
            f"return sum(values, {numeric}(0))",
            "       " + "^" * len(f"sum(values, {numeric}(0))"),
            "pyjs.CompilationError: sum() has an ambiguous numeric result "
            "across iterable branches [PYJS1104]",
            "help: Convert every branch to one item type. A represented float "
            "start can absorb ordinary numeric branches; an ordinary float "
            "start can absorb fixed-width integer branches.",
        ),
        filename="integer_start_float_branch.py",
    )


@pytest.mark.parametrize(
    ("annotation", "expression"),
    (
        ("int64 | float32", "divmod(value, 2.0)"),
        ("int64 | float32", "divmod(9.0, value)"),
        ("float32 | int64", "divmod(value, 2.0)"),
        ("float32 | int64", "divmod(9.0, value)"),
    ),
)
def test_divmod_rejects_union_contained_portable_floats(annotation, expression):
    source = f"""
    from pyjs import float32, int64, js

    @js
    def calculate(value: {annotation}):
        return {expression}
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "portable_float_union.py",
            5,
            f"return {expression}",
            "       " + "^" * len(expression),
            "pyjs.CompilationError: Portable fixed-width floats do not "
            "support 'divmod()' [PYJS1104]",
            "help: Use a supported arithmetic operation or convert both "
            "operands to ordinary float values first.",
        ),
        filename="portable_float_union.py",
    )


def test_divmod_rejects_ambiguous_fixed_and_boolean_branches():
    source = """
    from pyjs import int64, js

    @js
    def calculate(value: int64 | bool):
        return divmod(value, 2)
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "ambiguous_union_divmod.py",
            5,
            "return divmod(value, 2)",
            "       ^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: divmod() has an ambiguous numeric result "
            "across union branches [PYJS1104]",
            "help: Convert every branch to one numeric type, or include an "
            "ordinary float operand to select ordinary float results.",
        ),
        filename="ambiguous_union_divmod.py",
    )


@pytest.mark.parametrize("operator", ("//", "%", "**"))
def test_portable_float_rejects_unsupported_operations_during_analysis(operator):
    expression = f"float32(4.0) {operator} float32(2.0)"
    source = f"""
    from pyjs import float32, js

    @js
    def main() -> None:
        print({expression})
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "portable_float.py",
            6,
            f"print({expression})",
            "      " + "^" * len(expression),
            "pyjs.CompilationError: Portable fixed-width floats do not "
            f"support {operator!r} [PYJS1104]",
            "help: Use a supported arithmetic operation or convert both "
            "operands to ordinary float values first.",
        ),
        filename="portable_float.py",
    )


@pytest.mark.parametrize(
    ("expression", "operation"),
    (
        ("float32(4.0).__floordiv__(2.0)", "//"),
        ("float32(2.0).__rfloordiv__(4.0)", "//"),
        ("float32(5.0).__mod__(2.0)", "%"),
        ("float32(2.0).__rmod__(5.0)", "%"),
        ("float32(5.0).__floordiv__(float64(2.0))", "//"),
        ("float32(5.0).__mod__(int32(2))", "%"),
        ("float32(2.0).__pow__(2.0)", "**"),
        ("float32(2.0).__rpow__(2.0)", "**"),
        ("float32(5.0).__divmod__(2.0)", "divmod()"),
        ("float32(2.0).__rdivmod__(5.0)", "divmod()"),
        ("divmod(float32(5.0), float32(2.0))", "divmod()"),
        ("divmod(float32(33554434.0), 1.0)", "divmod()"),
        ("divmod(float32(5.0), float64(2.0))", "divmod()"),
        ("divmod(int32(5), float32(2.0))", "divmod()"),
    ),
)
def test_portable_float_rejects_unsupported_calls_during_analysis(
    expression,
    operation,
):
    underline_length = len(expression)
    if operation in {"**", "divmod()"} and ".__" in expression:
        underline_length = expression.index("(", expression.index(".__"))
    source = f"""
    from pyjs import float32, float64, int32, js

    @js
    def main() -> None:
        print({expression})
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "portable_float_call.py",
            6,
            f"print({expression})",
            "      " + "^" * underline_length,
            "pyjs.CompilationError: Portable fixed-width floats do not "
            f"support {operation!r} [PYJS1104]",
            "help: Use a supported arithmetic operation or convert both "
            "operands to ordinary float values first.",
        ),
        filename="portable_float_call.py",
    )


def test_portable_float_call_checks_use_the_explicit_method_receiver():
    assert_semantics(
        """
        from pyjs import float32, js

        @js
        def main() -> None:
            print((5.0).__floordiv__(2.0))
            print((5.0).__mod__(2.0))
            print((5.0).__floordiv__(float32(2.0)))
            print((2.0).__rfloordiv__(float32(5.0)))
            print((5.0).__mod__(float32(2.0)))
            print((2.0).__rmod__(float32(5.0)))
            quotient, remainder = divmod(5.0, 2.0)
            print(quotient)
            print(remainder)

        main()
        """
    )


@pytest.mark.parametrize(
    "expression",
    (
        "int8(1).__add__(int32(2))",
        "int8(5).__sub__(int32(2))",
        "int8(3).__mul__(int32(4))",
        "int8(1).__radd__(int32(2))",
        "int8(1).__rsub__(int32(2))",
        "int8(1).__add__(int16(2))",
        "int8(1).__add__(uint8(2))",
        "int8(1).__eq__(int32(1))",
        "int8(1).__lt__(int32(2))",
        "float32(1.0).__add__(float64(2.0))",
        "float32(6.0).__truediv__(float64(2.0))",
        "float32(1.0).__rtruediv__(float64(2.0))",
        "float32(1.0).__add__(int8(2))",
    ),
)
def test_explicit_numeric_dunders_reject_mixed_representations(expression):
    source = f"""
    from pyjs import float32, float64, int8, int16, int32, js, uint8

    @js
    def main() -> None:
        print({expression})
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "numeric_dunder.py",
            6,
            f"print({expression})",
            "      " + "^" * len(expression),
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be mixed implicitly [PYJS1104]",
            "help: Convert the values to one fixed-width type first.",
        ),
        filename="numeric_dunder.py",
    )


def test_numeric_dunder_keyword_arguments_use_the_same_representation_rules():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def main() -> None:
            print(int8(1).__add__(other=int8(2)))

        main()
        """
    )
    for expression in (
        "int8(1).__add__(other=int32(2))",
        "float32(1.0).__truediv__(other=int8(2))",
    ):
        source = f"""
    from pyjs import float32, int8, int32, js

    @js
    def main() -> None:
        print({expression})
    """
        assert_diagnostic(
            source,
            diagnostic_text(
                "numeric_dunder_keyword.py",
                6,
                f"print({expression})",
                "      " + "^" * len(expression),
                "pyjs.CompilationError: different fixed-width numeric types "
                "cannot be mixed implicitly [PYJS1104]",
                "help: Convert the values to one fixed-width type first.",
            ),
            filename="numeric_dunder_keyword.py",
        )


@pytest.mark.parametrize(
    "expression",
    (
        "float32.__floordiv__(float32(5.0), 2.0)",
        "int32.__add__(int32(1), 2)",
        "int8.__neg__(int8(1))",
        "int8.__abs__(int8(1))",
        "float32.__round__(float32(1.25), 1)",
        "int8.__name__",
    ),
)
def test_fixed_width_type_attributes_receive_a_located_diagnostic(expression):
    source = f"""
    from pyjs import float32, int8, int32, js

    @js
    def main() -> None:
        print({expression})
    """
    attribute = expression[: expression.index("(")] if "(" in expression else expression
    assert_diagnostic(
        source,
        diagnostic_text(
            "unbound_numeric.py",
            6,
            f"print({expression})",
            "      " + "^" * len(attribute),
            "pyjs.CompilationError: Runtime access to fixed-width type "
            "attributes is not supported [PYJS2001]",
            "help: Use fixed-width types in annotations, constructors, and "
            "instance operations.",
        ),
        filename="unbound_numeric.py",
    )


def test_static_array_python_constructor_rejects_nested_representation_changes():
    from pyjs import StaticArray, int8, int16

    with pytest.raises(TypeError) as caught:
        StaticArray[list[int8], 1]([[int16(1)]])

    assert str(caught.value) == ("a static array item requires an explicit conversion")


def test_runtime_static_array_alias_has_a_located_not_callable_diagnostic():
    assert_diagnostic(
        """
        from pyjs import StaticArray, int8, js

        Vec = StaticArray[int8, 2]

        @js
        def main() -> None:
            data: Vec = Vec([200, 1])
        """,
        diagnostic_text(
            "static_array_alias.py",
            8,
            "data: Vec = Vec([200, 1])",
            "            ^^^",
            "pyjs.CompilationError: Type alias 'Vec' cannot be called at "
            "runtime [PYJS1104]",
            "help: Call the underlying class directly or use the alias only "
            "in annotations.",
        ),
        filename="static_array_alias.py",
    )


@pytest.mark.parametrize(
    "expression",
    (
        "StaticArray[int8 | None, 1]([int16(1)])",
        "StaticArray[list[int8], 1]([[int16(1)]])",
        "StaticArray[tuple[int8], 1]([(int16(1),)])",
        "StaticArray[dict[str, int8], 1]([{'value': int16(1)}])",
    ),
)
def test_static_array_compound_items_reject_incompatible_values(expression):
    line = f"values = {expression}"
    assert_diagnostic(
        f"""\
        from pyjs import StaticArray, int8, int16, js

        @js
        def main() -> None:
            {line}
        """,
        diagnostic_text(
            "compound_array.py",
            5,
            line,
            " " * line.index("int16(1)") + "^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="compound_array.py",
    )


def test_static_array_typed_dict_items_reject_incompatible_fields():
    line = "values = StaticArray[Row, 1]([{'value': int16(1)}])"
    assert_diagnostic(
        f"""\
        from typing import TypedDict
        from pyjs import StaticArray, int8, int16, js

        class Row(TypedDict):
            value: int8

        @js
        def main() -> None:
            {line}
        """,
        diagnostic_text(
            "record_array.py",
            9,
            line,
            " " * line.index("int16(1)") + "^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="record_array.py",
    )


def test_static_array_callable_items_reject_incompatible_results():
    assert_diagnostic(
        """\
        from collections.abc import Callable
        from pyjs import StaticArray, int8, int16, js

        @js
        def wide() -> int16:
            return int16(1)

        @js
        def main() -> None:
            values = StaticArray[Callable[[], int8], 1]([wide])
        """,
        diagnostic_text(
            "callable_array.py",
            10,
            "values = StaticArray[Callable[[], int8], 1]([wide])",
            "                                             ^^^^",
            "pyjs.CompilationError: Value uses an incompatible nested "
            "representation [PYJS1104]",
            "help: Convert each represented value explicitly.",
        ),
        filename="callable_array.py",
    )


def test_same_represented_collection_lookups_and_comparisons_work():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def main() -> None:
            values = [int8(1), int8(2)]
            copied = [int8(1), int8(2)]
            members = {int8(1), int8(2)}
            mapping = {int8(1): "one"}
            print(int8(1) in values, values.count(int8(1)))
            print(values.index(int8(2)), values == copied)
            values.remove(int8(1))
            print(int8(1) in members, mapping[int8(1)], mapping.get(int8(1)))
            print(mapping.setdefault(int8(2), "two"), mapping.pop(int8(2)))
            print(members.isdisjoint({int8(3)}), members.issubset(copied))
            print(members.issuperset({int8(1)}), members >= {int8(1)})
            members.discard(int8(2))
            members.remove(int8(1))
            del mapping[int8(1)]
            print(len(values), len(members), len(mapping))

        main()
        """
    )


def test_represented_collections_accept_ordinary_numeric_lookups():
    assert_semantics(
        """
        from pyjs import int8, int64, js

        @js
        def main() -> None:
            narrow = [int8(0), int8(1)]
            print(1 in narrow, 256 in narrow)
            print(narrow.count(1), narrow.index(1))
            narrow.remove(1)

            wide_list: list[int64] = [int64(1), int64(2)]
            print(1 in wide_list, wide_list.count(2), wide_list.index(2))
            wide_list.remove(1)
            print(wide_list[0])

            wide_set: set[int64] = {int64(1)}
            print(1 in wide_set)
            wide_set.discard(1)
            print(len(wide_set))

            wide_mapping: dict[int64, str] = {int64(1): "one"}
            print(wide_mapping[1], wide_mapping.get(1), 1 in wide_mapping)
            print(wide_mapping.setdefault(2, "two"), wide_mapping.pop(2))
            del wide_mapping[1]
            print(len(wide_mapping))
            large: dict[int64, str] = {
                int64(9_223_372_036_854_775_807): "large"
            }
            print(large[9_223_372_036_854_775_807])

            ordinary = [1, 2]
            print(int64(1) in ordinary, ordinary.count(int64(2)))
            ordinary_set = {1, 2}
            print(int64(1) in ordinary_set)
            ordinary_mapping = {1: "one"}
            print(ordinary_mapping[int64(1)], int64(1) in ordinary_mapping)

        main()
        """
    )


def test_typed_dicts_compare_structurally_across_numeric_representations():
    assert_semantics(
        """
        from typing import TypedDict
        from pyjs import int8, js

        class Fixed(TypedDict):
            value: int8

        class Plain(TypedDict):
            value: int

        @js
        def matches(value: Fixed | None, other: dict[str, int]) -> bool:
            return value == other

        @js
        def main() -> None:
            fixed: Fixed = {"value": int8(1)}
            plain: Plain = {"value": 1}
            print(fixed == plain, plain == fixed)
            print(fixed != plain, plain != fixed)
            print(fixed == {"value": 1}, {"value": 1} == fixed)
            print(matches(fixed, {"value": 1}))
            print(matches(None, {"value": 1}))

        main()
        """
    )


def test_typed_dict_equality_rejects_incompatible_numeric_representations():
    assert_diagnostic(
        """\
        from typing import TypedDict
        from pyjs import int8, int16, js

        class Narrow(TypedDict):
            value: int8

        class Wide(TypedDict):
            value: int16

        @js
        def main(narrow: Narrow, wide: Wide) -> None:
            print(narrow == wide)
        """,
        diagnostic_text(
            "typed_dict_comparison.py",
            12,
            "print(narrow == wide)",
            "      ^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Collection equality uses incompatible "
            "item representations [PYJS1104]",
            "help: Convert both collections to the same item types first.",
        ),
        filename="typed_dict_comparison.py",
    )


def test_represented_collections_compare_with_ordinary_numeric_values():
    assert_semantics(
        """
        from pyjs import StaticArray, float32, int8, int64, js

        @js
        def main() -> None:
            print([int8(1)] == [1], [int8(1)] == [True])
            print([int8(0)] == [256], [float32(1.5)] == [1.5])
            print((int64(1),) == (1,), (int64(1),) != (1.5,))
            print({int64(1)} == {1}, {int64(1)} != {2})
            represented = {int64(1), int64(2)}
            ordinary = {1, 2, 3}
            print(represented.issubset(ordinary))
            print(ordinary.issuperset(represented))
            print(represented.isdisjoint({3}))
            print(represented <= ordinary, represented < ordinary)
            print({int64(1): "one"} == {1: "one"})
            print([[int64(1)]] == [[1]])
            print([int64(1)].__eq__([1]), (int64(1),).__ne__((2,)))
            print({int64(1)}.__eq__({1}))
            print({int64(1): "one"}.__eq__({1: "one"}))

            narrow = StaticArray[int8, 2]([1, 2])
            print(narrow == [1, 2], [1, 2] == narrow)
            wide = StaticArray[int64, 2]([1, 2])
            print(wide == [1, 2])
            nested = StaticArray[list[int8], 1]([[int8(1)]])
            print(nested == [[1]])

        main()
        """
    )


@pytest.mark.parametrize("annotation", [" -> Iterator[int]", ""])
def test_membership_falls_back_to_the_iteration_protocol(annotation):
    assert_semantics(
        f"""
        from collections.abc import Iterator

        from pyjs import js

        @js
        class Sequence:
            def __iter__(self){annotation}:
                return iter([1, 2, 3])

        @js
        def main() -> None:
            values = Sequence()
            print(2 in values, 4 not in values)

        main()
        """
    )


def test_getitem_only_membership_has_a_focused_diagnostic():
    assert_diagnostic(
        """
        from pyjs import js

        @js
        class Values:
            def __getitem__(self, index: int) -> int:
                if index >= 3:
                    raise IndexError(index)
                return index + 1

        @js
        def main() -> None:
            print(2 in Values())
        """,
        diagnostic_text(
            "membership.py",
            13,
            "print(2 in Values())",
            "      ^^^^^^^^^^^^^",
            "pyjs.CompilationError: Membership through __getitem__ is not "
            "supported [PYJS2001]",
            "help: Define __iter__(self) -> Iterator[T] or "
            "__contains__(self, value) -> bool.",
        ),
        filename="membership.py",
    )


def test_user_copy_method_keeps_its_declared_representation():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        class Factory:
            def copy(self) -> int8:
                return int8(127)

        @js
        def main() -> None:
            print(Factory().copy() + 1)

        main()
        """
    )


def test_static_array_copy_returns_an_ordinary_mutable_list():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            values = StaticArray[int8, 1]([int8(127)])
            copied = values.copy()
            copied.append(int8(1))
            print(len(copied), copied[0] + 1)

        main()
        """
    )


@pytest.mark.parametrize(
    "expression",
    (
        "values * 1",
        "1 * values",
        "values.__mul__(1)",
        "values.__rmul__(1)",
    ),
)
def test_static_array_repetition_is_rejected(expression):
    line = f"return {expression}"
    assert_diagnostic(
        f"""\
        from pyjs import StaticArray, int8, js

        @js
        def duplicate(
            values: StaticArray[int8, 1],
        ) -> object:
            {line}
        """,
        diagnostic_text(
            "array_repeat.py",
            5,
            line,
            "       " + "^" * len(expression),
            "pyjs.CompilationError: StaticArray repetition would change its "
            "declared length [PYJS1104]",
            "help: Copy items explicitly into a new StaticArray of that length.",
        ),
        filename="array_repeat.py",
    )


def test_static_array_repetition_is_rejected_by_cpython():
    from pyjs import StaticArray, int8

    values = StaticArray[int8, 1]([1])
    for operation in (
        lambda: values * 1,
        lambda: 1 * values,
        lambda: values.__mul__(1),
        lambda: values.__rmul__(1),
        lambda: values.__imul__(1),
        lambda: values.__imul__(1.0),
    ):
        with pytest.raises(TypeError, match="cannot change length"):
            operation()


def test_static_array_inplace_repetition_is_rejected_when_compiled():
    assert_diagnostic(
        """
        from pyjs import StaticArray, js

        @js
        def repeat(values: StaticArray[int, 1]) -> None:
            values *= 1
        """,
        diagnostic_text(
            "array_repeat.py",
            5,
            "values *= 1",
            "^^^^^^^^^^^",
            "pyjs.CompilationError: Static arrays do not support whole-array "
            "augmented assignment [PYJS1104]",
            "help: Assign individual items or create another static array.",
        ),
        filename="array_repeat.py",
    )


def test_static_array_concatenation_syntax_and_method_return_mutable_lists():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            values = StaticArray[int8, 1]([1])
            syntax = values + values
            explicit = values.__add__(values)
            syntax.append(int8(2))
            explicit.append(int8(3))
            print(syntax[2], explicit[2])

        main()
        """
    )


@pytest.mark.parametrize("literal", ("[*source]", "(*source,)", "[0, *source, 3]"))
def test_static_array_constructor_counts_starred_static_arrays(literal):
    length = 4 if "0," in literal else 2
    assert_semantics(
        f"""
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            source = StaticArray[int8, 2]([127, 1])
            copied = StaticArray[int8, {length}]({literal})
            print(copied[0], copied[-1])

        main()
        """
    )


def test_static_array_constructor_rejects_unknown_starred_lengths():
    assert_diagnostic(
        """
        from pyjs import StaticArray, int8, js

        @js
        def copy(source: list[int8]) -> StaticArray[int8, 2]:
            return StaticArray[int8, 2]([*source])
        """,
        diagnostic_text(
            "array_star.py",
            5,
            "return StaticArray[int8, 2]([*source])",
            "                             ^^^^^^^",
            "pyjs.CompilationError: StaticArray starred values require a "
            "statically known length [PYJS1104]",
            "help: Spread another StaticArray or list every item explicitly.",
        ),
        filename="array_star.py",
    )


def test_static_array_constructor_rejects_incompatible_starred_items():
    assert_diagnostic(
        """
        from pyjs import StaticArray, int8, int16, js

        @js
        def copy(
            source: StaticArray[int16, 2],
        ) -> StaticArray[int8, 2]:
            return StaticArray[int8, 2]([*source])
        """,
        diagnostic_text(
            "array_star.py",
            5,
            "return StaticArray[int8, 2]([*source])",
            "                             ^^^^^^^",
            "pyjs.CompilationError: Starred StaticArray items use an "
            "incompatible representation [PYJS1104]",
            "help: Convert each item explicitly before spreading the array.",
        ),
        filename="array_star.py",
    )


@pytest.mark.parametrize(
    ("expression", "marked", "message", "help_text"),
    (
        (
            "int16(1) in [int8(1)]",
            None,
            "Collection membership uses incompatible item representations",
            "Convert the searched value to the collection's item type first.",
        ),
        (
            "[int8(1)].count(int16(1))",
            "int16(1)",
            "Collection comparison uses an incompatible item representation",
            "Convert the compared value to the collection's item type first.",
        ),
        (
            "[int8(1)].index(int16(1))",
            "int16(1)",
            "Collection comparison uses an incompatible item representation",
            "Convert the compared value to the collection's item type first.",
        ),
        (
            "[int8(1)].remove(int16(1))",
            "int16(1)",
            "Collection comparison uses an incompatible item representation",
            "Convert the compared value to the collection's item type first.",
        ),
        (
            "int16(1) in {int8(1)}",
            None,
            "Collection membership uses incompatible item representations",
            "Convert the searched value to the collection's item type first.",
        ),
        (
            "{int8(1): 'one'}[int16(1)]",
            "int16(1)",
            "Dictionary lookup uses an incompatible key representation",
            "Convert the key to the dictionary's key type first.",
        ),
        (
            "{int8(1): 'one'}.get(int16(1))",
            "int16(1)",
            "Dictionary lookup uses an incompatible key representation",
            "Convert the key to the dictionary's key type first.",
        ),
        (
            "{int8(1): 'one'}.pop(int16(1))",
            "int16(1)",
            "Dictionary lookup uses an incompatible key representation",
            "Convert the key to the dictionary's key type first.",
        ),
        (
            "{int8(1): 'one'}.setdefault(int16(1), 'two')",
            "int16(1)",
            "Dictionary lookup uses an incompatible key representation",
            "Convert the key to the dictionary's key type first.",
        ),
        (
            "{int8(1)}.discard(int16(1))",
            "int16(1)",
            "Collection comparison uses an incompatible item representation",
            "Convert the compared value to the collection's item type first.",
        ),
        (
            "{int8(1)}.remove(int16(1))",
            "int16(1)",
            "Collection comparison uses an incompatible item representation",
            "Convert the compared value to the collection's item type first.",
        ),
        (
            "{int8(1)}.isdisjoint({int16(2)})",
            "{int16(2)}",
            "Set comparison uses incompatible item representations",
            "Convert both sets to the same item type first.",
        ),
        (
            "{int8(1)}.issubset({int16(1)})",
            "{int16(1)}",
            "Set comparison uses incompatible item representations",
            "Convert both sets to the same item type first.",
        ),
        (
            "{int8(1)}.issuperset({int16(1)})",
            "{int16(1)}",
            "Set comparison uses incompatible item representations",
            "Convert both sets to the same item type first.",
        ),
        (
            "[int8(1)] == [int16(1)]",
            None,
            "Collection equality uses incompatible item representations",
            "Convert both collections to the same item types first.",
        ),
        (
            "StaticArray[int8, 1]([1]) == [int16(1)]",
            None,
            "Collection equality uses incompatible item representations",
            "Convert both collections to the same item types first.",
        ),
        (
            "(int8(1),) == (int16(1),)",
            None,
            "Collection equality uses incompatible item representations",
            "Convert both collections to the same item types first.",
        ),
        (
            "{int8(1)} == {int16(1)}",
            None,
            "Collection equality uses incompatible item representations",
            "Convert both collections to the same item types first.",
        ),
        (
            "{int8(1)} < {int16(1)}",
            None,
            "Set comparison uses incompatible item representations",
            "Convert both sets to the same item type first.",
        ),
        (
            "{int8(1)} <= {int16(1)}",
            None,
            "Set comparison uses incompatible item representations",
            "Convert both sets to the same item type first.",
        ),
        (
            "{int8(1)} > {int16(1)}",
            None,
            "Set comparison uses incompatible item representations",
            "Convert both sets to the same item type first.",
        ),
        (
            "{int8(1)} >= {int16(1)}",
            None,
            "Set comparison uses incompatible item representations",
            "Convert both sets to the same item type first.",
        ),
        (
            "{int8(1): 'one'} == {int16(1): 'one'}",
            None,
            "Collection equality uses incompatible item representations",
            "Convert both collections to the same item types first.",
        ),
        (
            "[int8(1)].__contains__(int16(1))",
            "int16(1)",
            "Collection comparison uses an incompatible item representation",
            "Convert the compared value to the collection's item type first.",
        ),
        (
            "(int8(1),).__contains__(int16(1))",
            "int16(1)",
            "Collection comparison uses an incompatible item representation",
            "Convert the compared value to the collection's item type first.",
        ),
        (
            "{int8(1)}.__contains__(int16(1))",
            "int16(1)",
            "Collection comparison uses an incompatible item representation",
            "Convert the compared value to the collection's item type first.",
        ),
        *(
            (
                expression,
                marked,
                "Collection comparison uses incompatible item representations",
                "Convert both collections to the same item types first.",
            )
            for expression, marked in (
                ("[int8(1)].__eq__([int16(1)])", "[int16(1)]"),
                ("[int8(1)].__ne__([int16(1)])", "[int16(1)]"),
                ("(int8(1),).__eq__((int16(1),))", "(int16(1),)"),
                ("(int8(1),).__ne__((int16(1),))", "(int16(1),)"),
                ("{int8(1)}.__eq__({int16(1)})", "{int16(1)}"),
                ("{int8(1)}.__ne__({int16(1)})", "{int16(1)}"),
                ("{int8(1)}.__lt__({int16(1)})", "{int16(1)}"),
                ("{int8(1)}.__le__({int16(1)})", "{int16(1)}"),
                ("{int8(1)}.__gt__({int16(1)})", "{int16(1)}"),
                ("{int8(1)}.__ge__({int16(1)})", "{int16(1)}"),
                (
                    "{int8(1): 'one'}.__eq__({int16(1): 'one'})",
                    "{int16(1): 'one'}",
                ),
                (
                    "{int8(1): 'one'}.__ne__({int16(1): 'one'})",
                    "{int16(1): 'one'}",
                ),
            )
        ),
    ),
)
def test_incompatible_collection_operations_are_rejected(
    expression,
    marked,
    message,
    help_text,
):
    line = f"print({expression})"
    marked = expression if marked is None else marked
    marker = " " * line.index(marked) + "^" * len(marked)
    assert_diagnostic(
        f"""\
        from pyjs import StaticArray, int8, int16, js

        @js
        def main() -> None:
            {line}
        """,
        diagnostic_text(
            "collection.py",
            5,
            line,
            marker,
            f"pyjs.CompilationError: {message} [PYJS1104]",
            f"help: {help_text}",
        ),
        filename="collection.py",
    )


def test_chained_collection_comparisons_preserve_item_representations():
    assert_diagnostic(
        """\
        from pyjs import int8, int16, js

        @js
        def main() -> None:
            print([int8(1)] == [int16(1)] == [int16(1)])
        """,
        diagnostic_text(
            "chain.py",
            5,
            "print([int8(1)] == [int16(1)] == [int16(1)])",
            "      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Collection equality uses incompatible "
            "item representations [PYJS1104]",
            "help: Convert both collections to the same item types first.",
        ),
        filename="chain.py",
    )


def test_syntax_lowered_dunders_preserve_compound_return_representations():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        class Box:
            def __getitem__(self, index: int) -> list[int8]:
                return [int8(127)]

        @js
        def main() -> None:
            print(Box()[0][0] + 1)

        main()
        """
    )


def test_dictionary_deletion_validates_the_key_representation():
    assert_diagnostic(
        """\
        from pyjs import int8, int16, js

        @js
        def main() -> None:
            values = {int8(1): "one"}
            del values[int16(1)]
        """,
        diagnostic_text(
            "mapping_delete.py",
            6,
            "del values[int16(1)]",
            "           ^^^^^^^^",
            "pyjs.CompilationError: Dictionary lookup uses an incompatible "
            "key representation [PYJS1104]",
            "help: Convert the key to the dictionary's key type first.",
        ),
        filename="mapping_delete.py",
    )


@pytest.mark.parametrize(
    "annotation",
    (
        "int8 | int8",
        "Union[int8, int8]",
        "int8 | int8 | None",
        "Optional[int8 | int8]",
    ),
)
def test_duplicate_represented_union_members_are_normalized(annotation):
    assert_semantics(
        f"""
        from typing import Optional, Union

        from pyjs import int8, js

        @js
        def increment(value: {annotation}) -> int8:
            if value is None:
                return int8(0)
            return value + 1

        def main() -> None:
            print(increment(int8(127)))

        main()
        """
    )


def test_duplicate_represented_union_aliases_are_normalized():
    assert_semantics(
        """
        from pyjs import int8, js

        Small = int8

        @js
        def increment(value: int8 | Small) -> int8:
            return value + 1

        def main() -> None:
            print(increment(int8(127)))

        main()
        """
    )
