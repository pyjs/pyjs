import asyncio
import base64
import shutil
import subprocess
import sys

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.tooling.browser import Browser
from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from tests.backend_semantics import (
    APPLICATION_GENERIC_UNION_ORDER_CONTRACT,
    ASSERT_NARROWING_CONTRACT,
    BACKEND_CONTRACTS,
    BINARY_POWER_CONTRACT,
    BOOLEAN_NUMERIC_CONTRACT,
    CALLABLE_INPUT_CONTRACT,
    CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT,
    COLLECTION_NAME_CONTRACT,
    CUSTOM_EXCEPTION_CONTRACT,
    DATACLASS_NAN_IDENTITY_SOURCE,
    DIRECT_UNION_RESULT_CONTRACT,
    EXCEPTION_OBJECT_CONTRACT,
    FIELD_ASSIGNMENT_CONTRACT,
    GENERATOR_CLEANUP_CONTRACT,
    GENERIC_OPERATOR_CONTRACT,
    GENERIC_UNION_ORDER_CONTRACT,
    INHERITED_FACTORY_FIELD_CONTRACT,
    INHERITED_FIELD_ASSIGNMENT_CONTRACT,
    INTEGER_LIST_MEMBERSHIP_CONTRACT,
    LITERAL_FIELD_ASSIGNMENT_CONTRACT,
    LITERAL_SEQUENCE_REFLECTION_CONTRACT,
    MAPPING_LOOKUP_REPRESENTATION_CONTRACT,
    NESTED_CONDITIONAL_CONTRACT,
    NUMERIC_NAME_CONTRACT,
    PORTABLE_FAILURE_SOURCES,
    POSTPONED_DATACLASS_CONTRACT,
    PROPERTY_FIELD_OVERRIDE_CONTRACT,
    RANGE_NUMERIC_LOOKUP_CONTRACT,
    RECURSIVE_EQUALITY_CONTRACT,
    RECURSIVE_OPTIONAL_CONTRACT,
    RECURSIVE_TREE_CONTRACT,
    REVERSED_PROTOCOL_CONTRACT,
    SEQUENCE_REFLECTION_CONTRACT,
    STRING_DICTIONARY_MEMBERSHIP_CONTRACT,
    STRUCTURAL_OPERATOR_CONTRACT,
    UNION_KEY_REPRESENTATION_CONTRACT,
    UNPACK_FIELD_CONTRACT,
    nominal_object_contract,
)


def test_boolean_arithmetic_has_an_explicit_wasm_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly call target __add__ is not implemented"):
        transpile_webassembly(BOOLEAN_NUMERIC_CONTRACT.source)


@pytest.mark.parametrize(("contract", "message"), [
    (INTEGER_LIST_MEMBERSHIP_CONTRACT, "WebAssembly call target __contains__ is not implemented"),
    (STRING_DICTIONARY_MEMBERSHIP_CONTRACT, "WebAssembly value type dict__str_str is not implemented"),
])
def test_membership_contract_has_an_explicit_wasm_boundary(contract, message):
    with pytest.raises(WebAssemblyUnsupported) as error:
        transpile_webassembly(contract.source)
    assert str(error.value) == message


def test_range_lookup_keeps_the_wasm_first_class_range_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type range is not implemented"):
        transpile_webassembly(RANGE_NUMERIC_LOOKUP_CONTRACT.source)


def test_reference_tuple_contract_keeps_the_wasm_collection_boundary():
    from tests.backend_semantics import REFERENCE_TUPLE_CONTRACT
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly(REFERENCE_TUPLE_CONTRACT.source)
    assert str(caught.value) == "WebAssembly value type tuple__str__variadic is not implemented"


def test_list_copy_contract_keeps_the_wasm_constructor_boundary():
    from tests.backend_semantics import LIST_COPY_CONTRACT
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly(LIST_COPY_CONTRACT.source)
    assert str(caught.value) == (
        "WebAssembly call target list__int is not implemented at line 4"
    )


def test_extracted_union_result_reaches_the_wasm_value_boundary():
    from tests.backend_semantics import UNION_CALLBACK_RESULT_CONTRACT
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type str is not implemented"):
        transpile_webassembly(UNION_CALLBACK_RESULT_CONTRACT.source)


@pytest.mark.parametrize("expression", ['dict(first="one")', 'dict(**{"first": "one"})'])
def test_dictionary_keywords_keep_the_wasm_collection_boundary(expression):
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly len currently requires a list"):
        transpile_webassembly(f"def main() -> int:\n    return len({expression})\n")


@pytest.mark.parametrize("contract", [SEQUENCE_REFLECTION_CONTRACT, LITERAL_SEQUENCE_REFLECTION_CONTRACT])
def test_sequence_reflection_reaches_the_wasm_string_boundary(contract):
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type str is not implemented"):
        transpile_webassembly(contract.source)


@pytest.mark.parametrize("contract", [DIRECT_UNION_RESULT_CONTRACT, GENERIC_UNION_ORDER_CONTRACT],
                         ids=["direct-method", "generic-container"])
def test_union_result_keeps_the_wasm_value_boundary(contract):
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type str is not implemented"):
        transpile_webassembly(contract.source)


def test_application_generic_union_orders_keep_the_wasm_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly union value storage is not implemented"):
        transpile_webassembly(APPLICATION_GENERIC_UNION_ORDER_CONTRACT.source)


def test_bounded_text_search_keeps_a_focused_wasm_boundary():
    from tests.backend_semantics import BOUNDED_TEXT_SEARCH_CONTRACT
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type str is not implemented"):
        transpile_webassembly(BOUNDED_TEXT_SEARCH_CONTRACT.source)


def test_bytes_construction_keeps_the_wasm_binary_boundary():
    from tests.backend_semantics import BYTES_CONSTRUCTION_CONTRACT
    with pytest.raises(CompilationError, match="bytes literals are not supported"):
        transpile_webassembly(BYTES_CONSTRUCTION_CONTRACT.source)


@pytest.mark.parametrize("expression", ["range(Index())", "enumerate([1], Index())"])
def test_index_constructors_keep_the_wasm_iteration_boundary(expression):
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly iteration currently requires a list"):
        transpile_webassembly(f'''
            class Index:
                def __index__(self) -> int:
                    return 3
            def main() -> int:
                total = 0
                for value in {expression}:
                    total += 1
                return total
        ''')


def test_slice_values_keep_the_wasm_boundary():
    from tests.backend_semantics import SLICE_VALUE_CONTRACT
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type slice is not implemented"):
        transpile_webassembly(SLICE_VALUE_CONTRACT.source)


def test_callable_iterable_views_reach_a_focused_wasm_boundary():
    from tests.backend_semantics import CALLABLE_ITERABLE_CONTRACT
    with pytest.raises(WebAssemblyUnsupported, match="callable|Iterable"):
        transpile_webassembly(CALLABLE_ITERABLE_CONTRACT.source)


def test_nested_literal_context_reaches_the_wasm_iterable_boundary():
    from tests.backend_semantics import ITERABLE_LITERAL_CONTEXT_CONTRACT
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type Iterable__list__list__int is not implemented"):
        transpile_webassembly(ITERABLE_LITERAL_CONTEXT_CONTRACT.source)

LIST_MUTATION_SOURCE = """
def accumulate(values: list[int]) -> int:
    values[-1] = 4
    total = len(values)
    for value in values:
        total = total + value
        if total < 9:
            values.append(1)
        if total >= 10:
            break
    return total + len(values)


def main() -> int:
    return accumulate([1, 2])
"""


def test_callback_input_views_reach_the_wasm_object_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type object is not implemented"):
        transpile_webassembly(CALLABLE_INPUT_CONTRACT.source)


def test_default_callable_views_reach_the_wasm_callable_boundary():
    from tests.backend_semantics import CALLABLE_DEFAULT_CONTRACT
    with pytest.raises(WebAssemblyUnsupported, match="Callable|callable|function values"):
        transpile_webassembly(CALLABLE_DEFAULT_CONTRACT.source)


def node():
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node.js is required to execute WebAssembly tests")
    return executable


def test_print_has_an_explicit_unsupported_output_diagnostic():
    with pytest.raises(WebAssemblyUnsupported, match=r"WebAssembly print\(\) output is not implemented at line 2"):
        transpile_webassembly("def main() -> int:\n    print('message')\n    return 0")


def test_generator_cleanup_has_a_focused_unsupported_diagnostic():
    with pytest.raises(CompilationError, match="generator suspension is not implemented by this backend"):
        transpile_webassembly(GENERATOR_CLEANUP_CONTRACT.source)


@pytest.mark.parametrize("exception", ["AttributeError", "ValueError"])
def test_exception_raising_has_a_focused_unsupported_diagnostic(exception):
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly exception raising is not implemented"):
        transpile_webassembly(f'def main() -> int:\n    raise {exception}("missing")\n')


@pytest.mark.parametrize("contract", [CUSTOM_EXCEPTION_CONTRACT, EXCEPTION_OBJECT_CONTRACT],
                         ids=["custom", "owned"])
def test_custom_exception_contract_keeps_wasm_handler_boundary(contract):
    with pytest.raises(CompilationError) as caught:
        transpile_webassembly(contract.source)
    diagnostic = caught.value.diagnostic
    assert diagnostic.code.value == "PYJS2001"
    assert diagnostic.message == "native IR exception handlers are not implemented"
    assert diagnostic.help == (
        "Move exception handling outside this backend until it implements shared IR exception regions.",
    )
    span = diagnostic.primary.span
    assert span.source.lines[span.start_position.line].strip() == "try:"


def test_generic_fromkeys_reaches_the_mapping_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="value type dict__int_int is not implemented"):
        transpile_webassembly('''
            def main() -> int:
                values = dict.fromkeys([1, 2], 3)
                return len(values)
        ''')


@pytest.mark.parametrize("name, argument", [("hash", "1"), ("ord", "'x'")])
def test_native_value_builtins_keep_located_wasm_boundaries(name, argument):
    with pytest.raises(WebAssemblyUnsupported, match=f"WebAssembly call target {name} is not implemented at line 2"):
        transpile_webassembly(f"def main() -> int:\n    return {name}({argument})\n")


def execute(tmp_path, source: str, arguments: str = "") -> str:
    module = transpile_webassembly(source)
    path = module.write(tmp_path / "program.wasm")
    script = (
        "const fs=require('fs');"
        "WebAssembly.instantiate(fs.readFileSync(process.argv[1]))"
        f".then(({{instance}})=>console.log(instance.exports.main({arguments}).toString()))"
        ".catch(error=>{console.error(error);process.exit(1)})"
    )
    return subprocess.run(
        [node(), "-e", script, str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_unpacking_fields_keeps_the_wasm_checked_sequence_boundary():
    # The shared list-arity helper requires object storage unavailable here;
    # this source was already unsupported before the JS unpacking improvement.
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type object is not implemented"):
        transpile_webassembly(UNPACK_FIELD_CONTRACT.source)


def test_postponed_dataclass_shared_contract(tmp_path):
    assert execute(tmp_path, POSTPONED_DATACLASS_CONTRACT) == "42"


def test_wasm_uses_python_bodies_not_javascript_clients(tmp_path):
    from tests.backend_semantics import CLIENT_IMPLEMENTATIONS_SOURCE
    assert execute(tmp_path, CLIENT_IMPLEMENTATIONS_SOURCE) == "107"


def test_dataclass_equality_retains_explicit_wasm_object_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="value type object is not implemented"):
        transpile_webassembly(DATACLASS_NAN_IDENTITY_SOURCE)


async def execute_in_browser(binary: bytes, arguments: str) -> float:
    encoded = base64.b64encode(binary).decode()
    async with Browser() as browser:
        page = await browser.new_page("data:text/html,<title>PyJS WASM</title>")
        result = await page.evaluate(
            f"""(async () => {{
                const encoded = {encoded!r};
                const bytes = Uint8Array.from(atob(encoded),
                    (character) => character.charCodeAt(0));
                const {{instance}} = await WebAssembly.instantiate(bytes);
                return Number(instance.exports.main({arguments}));
            }})()"""
        )
        assert page.exceptions == []
        return result


def test_webassembly_binary_executes_calls_and_control_flow(tmp_path):
    result = execute(
        tmp_path,
        """
def choose(flag: bool, left: int, right: int) -> int:
    if flag:
        result = left + 1
    else:
        result = right + 2
    return result


def main() -> int:
    return choose(True, 40, 0)
""",
    )

    assert result == "41"


@pytest.mark.parametrize(
    "contract",
    BACKEND_CONTRACTS.values(),
    ids=BACKEND_CONTRACTS,
)
def test_webassembly_runs_shared_numeric_contracts(tmp_path, contract):
    result = int(execute(tmp_path, contract.source))

    assert result == 0, contract.failure(result)


def test_webassembly_binary_power_contract(tmp_path):
    test_webassembly_runs_shared_numeric_contracts(tmp_path, BINARY_POWER_CONTRACT)


def test_webassembly_structural_operator_contract(tmp_path):
    test_webassembly_runs_shared_numeric_contracts(tmp_path, STRUCTURAL_OPERATOR_CONTRACT)


def test_assert_narrowing_retains_the_webassembly_union_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly union value storage is not implemented"):
        transpile_webassembly(ASSERT_NARROWING_CONTRACT.source)


def test_instance_assertion_contract_keeps_the_wasm_exception_boundary():
    from tests.backend_semantics import ASSERT_INSTANCE_STATE_CONTRACT
    with pytest.raises(
        CompilationError, match="native IR exception handlers are not implemented",
    ):
        transpile_webassembly(ASSERT_INSTANCE_STATE_CONTRACT.source)


def test_webassembly_reversed_protocol_contract(tmp_path):
    test_webassembly_runs_shared_numeric_contracts(tmp_path, REVERSED_PROTOCOL_CONTRACT)


def test_webassembly_runs_shared_field_assignment_contract(tmp_path):
    result = int(execute(tmp_path, FIELD_ASSIGNMENT_CONTRACT.source))
    assert result == 0, FIELD_ASSIGNMENT_CONTRACT.failure(result)


def test_shared_empty_literal_sibling_contract(tmp_path):
    from tests.backend_semantics import EMPTY_LITERAL_SIBLING_CONTRACT
    result = int(execute(tmp_path, EMPTY_LITERAL_SIBLING_CONTRACT.source))
    assert result == 0, EMPTY_LITERAL_SIBLING_CONTRACT.failure(result)


@pytest.mark.parametrize("contract", [INHERITED_FIELD_ASSIGNMENT_CONTRACT, CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT,
                                     INHERITED_FACTORY_FIELD_CONTRACT],
                         ids=["initializer", "class-body", "inherited_factory"])
def test_inherited_fields_have_an_explicit_webassembly_boundary(contract):
    with pytest.raises(WebAssemblyUnsupported, match="class inheritance is not implemented"):
        transpile_webassembly(contract.source)


def test_mapping_lookup_contract_has_explicit_tuple_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type tuple__int_list__float is not implemented"):
        transpile_webassembly(MAPPING_LOOKUP_REPRESENTATION_CONTRACT.source)


def test_union_key_representation_contract_has_explicit_webassembly_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type dict__intUNoneType_int is not implemented"):
        transpile_webassembly(UNION_KEY_REPRESENTATION_CONTRACT.source)


def test_reflected_mapping_union_keeps_the_webassembly_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type dict__int_int is not implemented"):
        transpile_webassembly('''
def main() -> int:
    left = {1: 2}
    right = {3: 4}
    return len(left.__ror__(right))
''')


def test_scalar_set_relations_have_an_explicit_webassembly_boundary():
    from tests.backend_semantics import SCALAR_SET_RELATIONS_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type set__intUNoneType is not implemented"):
        transpile_webassembly(SCALAR_SET_RELATIONS_CONTRACT.source)


@pytest.mark.parametrize("target, message", [
    ("list[int8]", "WebAssembly call target list__int is not implemented"),
    ("tuple[int8, ...]", "WebAssembly value type tuple__int__variadic is not implemented"),
])
def test_explicit_sequence_constructor_has_a_webassembly_capability_boundary(target, message):
    with pytest.raises(WebAssemblyUnsupported, match=message):
        transpile_webassembly(f'''from pyjs import int8
def main() -> int:
    source = [int8(127)]
    copied = {target}(source)
    return int(copied[0] + 1)
''')


def test_set_constructor_representation_has_an_explicit_webassembly_boundary():
    from tests.backend_semantics import SET_CONSTRUCTOR_REPRESENTATION_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly union value storage is not implemented"):
        transpile_webassembly(SET_CONSTRUCTOR_REPRESENTATION_CONTRACT.source)


def test_generic_operator_contract_has_explicit_inheritance_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="class inheritance is not implemented"):
        transpile_webassembly(GENERIC_OPERATOR_CONTRACT.source)


@pytest.mark.parametrize("contract", [RECURSIVE_TREE_CONTRACT, RECURSIVE_OPTIONAL_CONTRACT, RECURSIVE_EQUALITY_CONTRACT])
def test_recursive_tree_contract_has_explicit_storage_boundary(contract):
    with pytest.raises(WebAssemblyUnsupported, match="union value storage is not implemented"):
        transpile_webassembly(contract.source)


def test_webassembly_application_collection_names(tmp_path):
    # Shared analysis now reaches the backend's existing nominal layout limit.
    with pytest.raises(WebAssemblyUnsupported, match="lists require an inferred item type"):
        transpile_webassembly(COLLECTION_NAME_CONTRACT.source)


def test_webassembly_numeric_name_contract_has_explicit_text_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="value type str is not implemented"):
        transpile_webassembly(NUMERIC_NAME_CONTRACT.source)


@pytest.mark.parametrize("name", ["str", "object"])
def test_webassembly_nominal_erasure_contract_has_explicit_inheritance_boundary(name):
    with pytest.raises(WebAssemblyUnsupported, match="class inheritance is not implemented"):
        transpile_webassembly(nominal_object_contract(name).source)


def test_webassembly_literal_field_contract_has_explicit_set_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="value type set__intUstr is not implemented"):
        transpile_webassembly(LITERAL_FIELD_ASSIGNMENT_CONTRACT.source)


def test_webassembly_property_override_keeps_unsupported_analysis_boundary():
    with pytest.raises(CompilationError, match="Function returns str.*NoneType, not str"):
        transpile_webassembly(PROPERTY_FIELD_OVERRIDE_CONTRACT.source)


def test_webassembly_nested_conditional_order(tmp_path):
    contract = NESTED_CONDITIONAL_CONTRACT
    result = int(execute(tmp_path, contract.source))
    assert result == 0, contract.failure(result)


@pytest.mark.parametrize(
    "source",
    PORTABLE_FAILURE_SOURCES.values(),
    ids=PORTABLE_FAILURE_SOURCES,
)
def test_webassembly_rejects_shared_portable_numeric_failures(tmp_path, source):
    with pytest.raises(subprocess.CalledProcessError):
        execute(tmp_path, source)


def test_webassembly_binary_output_is_deterministic():
    source = """
def double(value: int) -> int:
    return value * 2


def main() -> int:
    return double(21)
"""

    assert transpile_webassembly(source).binary == transpile_webassembly(source).binary


def test_webassembly_state_machine_executes_a_scalar_loop(tmp_path):
    result = execute(
        tmp_path,
        """
def accumulate(limit: int) -> int:
    total = 0
    current = 0
    while current < limit:
        total = total + current
        current = current + 1
    return total


def main() -> int:
    return accumulate(5)
""",
    )

    assert result == "10"


def test_webassembly_executes_an_ordinary_imported_helper(tmp_path, monkeypatch):
    module_name = "pyjs_webassembly_imported_helper"
    (tmp_path / f"{module_name}.py").write_text(
        "ANNOTATED_MODULE_VALUE: int = 1\n\n"
        "def increment(value: int) -> int:\n    return value + 1\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(module_name, None)

    result = execute(
        tmp_path,
        f"""
from {module_name} import increment


def main() -> int:
    return increment(41)
""",
    )

    assert result == "42"


def test_webassembly_executes_float_control_flow_and_arithmetic(tmp_path):
    source = """
def main(left: float, right: float) -> float:
    if left > right:
        return left / 2.0
    return -(right + 1.0)
"""

    assert execute(tmp_path, source, "8.5, 2.0") == "4.25"
    assert execute(tmp_path, source, "1.0, 3.5") == "-4.5"


def test_webassembly_float_division_by_zero_traps(tmp_path):
    source = """
def main(numerator: float, denominator: float) -> float:
    return numerator / denominator
"""

    with pytest.raises(subprocess.CalledProcessError):
        execute(tmp_path, source, "1.0, 0.0")


def test_webassembly_float_abs_and_isfinite_match_python(tmp_path):
    source = """
import math


def main(value: float) -> float:
    if not math.isfinite(value):
        return -1.0
    return abs(value)
"""

    assert execute(tmp_path, source, "-3.25") == "3.25"
    assert execute(tmp_path, source, "Infinity") == "-1"


def test_webassembly_integer_abs_matches_python(tmp_path):
    assert (
        execute(
            tmp_path,
            """
def main(value: int) -> int:
    return abs(value) + abs(True)
""",
            "-41n",
        )
        == "42"
    )


def test_webassembly_converts_integer_operands_in_float_arithmetic(tmp_path):
    source = """
def main(value: float, count: int) -> float:
    if not value:
        return 0.0
    return value + count
"""

    assert execute(tmp_path, source, "1.5, 2n") == "3.5"
    assert execute(tmp_path, source, "0.0, 2n") == "0"


def test_webassembly_uses_shared_numeric_formats_at_boundaries(tmp_path):
    result = execute(
        tmp_path,
        """
from pyjs import float32, float64, int8, int16, int32, int64
from pyjs import uint8, uint16, uint32


class Reading:
    signed: int16
    unsigned: uint16

    def __init__(self, signed: int16, unsigned: uint16) -> None:
        self.signed = signed
        self.unsigned = unsigned


def signed(value: int8) -> int32:
    return int32(value)


def unsigned(value: uint8) -> uint32:
    return uint32(value)


def half(value: float32) -> float64:
    return float64(value / float32(2.0))


def wide(value: int64) -> int64:
    return value + 1


def narrow(value: int64) -> int64:
    return value - 1


def identity(value: int64) -> int64:
    return value


def wrap(value: int8) -> int8:
    return (value + 30) * 3


def main() -> int:
    reading = Reading(-2, -1)
    if signed(-1) != -1:
        return 1
    if unsigned(-1) != 255:
        return 2
    if reading.signed != -2:
        return 3
    if reading.unsigned != 65535:
        return 4
    if half(float32(5.0)) != 2.5:
        return 5
    if wide(9007199254740992) != 9007199254740993:
        return 6
    if wide(9223372036854775807) >= 0:
        return 7
    if narrow(wide(9223372036854775807)) != 9223372036854775807:
        return 8
    if identity(-9223372036854775808) >= 0:
        return 9
    if wrap(100) != -122:
        return 10
    if int8(130.9) != -126:
        return 11
    return 37
""",
    )

    assert result == "37"


def test_webassembly_normalizes_shared_formats_at_the_host_boundary(tmp_path):
    assert (
        execute(
            tmp_path,
            """
from pyjs import uint8, uint16


def main(value: uint8) -> uint16:
    return uint16(value)
""",
            "-1",
        )
        == "255"
    )
    assert (
        execute(
            tmp_path,
            """
from pyjs import int8, int16


def main(value: int8) -> int16:
    return int16(value)
""",
            "255",
        )
        == "-1"
    )


def test_webassembly_float_module_executes_in_a_managed_browser():
    compilation = transpile_webassembly(
        """
def main(numerator: float, denominator: float) -> float:
    if denominator == 0.0:
        return 1.0
    return numerator / denominator
"""
    )

    result = asyncio.run(execute_in_browser(compilation.binary, "9.0, 4.0"))

    assert result == 2.25


def test_webassembly_gc_objects_execute_constructors_fields_and_methods(tmp_path):
    result = execute(
        tmp_path,
        """
class Gauge:
    def __init__(self, value: float, enabled: bool):
        self.value = value
        self.enabled = enabled

    def adjust(self, amount: float) -> float:
        if self.enabled:
            self.value = self.value + amount
        return self.value


def identity(gauge: Gauge) -> Gauge:
    return gauge


def main() -> float:
    gauge = identity(Gauge(enabled=True, value=40.5))
    return gauge.adjust(1.5)
""",
    )

    assert result == "42"


def test_webassembly_gc_objects_execute_in_a_managed_browser():
    compilation = transpile_webassembly(
        """
class Counter:
    def __init__(self, value: int):
        self.value = value
        self.next = self

    def increment(self, amount: int) -> int:
        self.next = Counter(self.value + amount)
        return self.next.value


def main() -> int:
    counter = Counter(40)
    return counter.increment(2)
"""
    )

    result = asyncio.run(execute_in_browser(compilation.binary, ""))

    assert result == 42


def test_webassembly_gc_lists_append_resize_and_index(tmp_path):
    result = execute(
        tmp_path,
        """
Values = list[float]


def use(values: Values) -> Values:
    values.append(3.0)
    values.append(4.0)
    values.append(5.0)
    values.append(6.0)
    return values


def main() -> float:
    values: list[float] = [1.5, 2.0]
    result = use(values)
    return result[0] + result[-1]
""",
    )

    assert result == "7.5"


def test_webassembly_gc_list_bounds_fail_cleanly(tmp_path):
    source = """
def main(index: int) -> int:
    values: list[int] = [40, 2]
    return values[index]
"""

    with pytest.raises(subprocess.CalledProcessError):
        execute(tmp_path, source, "2n")
    with pytest.raises(subprocess.CalledProcessError):
        execute(tmp_path, source, "-3n")


def test_webassembly_gc_list_assignment_bounds_fail_cleanly(tmp_path):
    source = """
def main(index: int) -> int:
    values: list[int] = [40, 2]
    values[index] = 3
    return values[0]
"""

    with pytest.raises(subprocess.CalledProcessError):
        execute(tmp_path, source, "2n")
    with pytest.raises(subprocess.CalledProcessError):
        execute(tmp_path, source, "-3n")


def test_webassembly_gc_lists_mutate_during_iteration(tmp_path):
    assert execute(tmp_path, LIST_MUTATION_SOURCE) == "15"


def test_webassembly_gc_discovers_an_empty_list_used_only_by_len(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> int:
    values: list[float] = []
    return len(values)
""",
    )

    assert result == "0"


def test_webassembly_gc_list_assignment_preserves_python_evaluation_order(
    tmp_path,
):
    result = execute(
        tmp_path,
        """
def assigned(events: list[int]) -> int:
    events.append(1)
    return 42


def receiver(events: list[int], values: list[int]) -> list[int]:
    events.append(2)
    return values


def index(events: list[int]) -> int:
    events.append(3)
    return -1


def main() -> int:
    events: list[int] = []
    values = [0, 0]
    receiver(events, values)[index(events)] = assigned(events)
    return events[0] * 100 + events[1] * 10 + events[2] + values[-1]
""",
    )

    assert result == "165"


def test_webassembly_gc_lists_hold_application_objects(tmp_path):
    result = execute(
        tmp_path,
        """
class Point:
    def __init__(self, x: float):
        self.x = x


class Path:
    def __init__(self, points: list[Point]):
        self.points = points

    def add(self, point: Point):
        self.points.append(point)

    def last(self) -> float:
        return self.points[-1].x


def main() -> float:
    path = Path([Point(1.0), Point(2.0)])
    path.add(Point(3.0))
    return path.last()
""",
    )

    assert result == "3"


def test_webassembly_gc_lists_execute_in_a_managed_browser():
    compilation = transpile_webassembly(LIST_MUTATION_SOURCE)

    result = asyncio.run(execute_in_browser(compilation.binary, ""))

    assert result == 15


def test_webassembly_gc_slice_rejects_inheritance():
    with pytest.raises(WebAssemblyUnsupported, match="inheritance"):
        transpile_webassembly(
            """
class Base:
    def value(self) -> int:
        return 1


class Derived(Base):
    pass


def main() -> int:
    return Derived().value()
"""
        )


def test_webassembly_gc_recursive_fields_execute_nested_object_mutation(tmp_path):
    result = execute(
        tmp_path,
        """
class Node:
    def __init__(self, value: int):
        self.value = value
        self.next = self

    def append(self, value: int) -> Node:
        self.next = Node(value)
        return self.next


def read(node: Node) -> int:
    return node.value


def main() -> int:
    head = Node(40)
    tail = head.append(2)
    return read(head.next) + read(tail)
""",
    )

    assert result == "4"


def test_webassembly_gc_group_supports_mutually_referencing_classes(tmp_path):
    result = execute(
        tmp_path,
        """
class Left:
    def __init__(self, value: int):
        self.value = value

    def connect(self, right: Right):
        self.right = right


class Right:
    def __init__(self, value: int):
        self.value = value

    def connect(self, left: Left):
        self.left = left


def main() -> int:
    left = Left(20)
    right = Right(2)
    left.connect(right)
    right.connect(left)
    return left.right.value + right.left.value
""",
    )

    assert result == "22"


def test_webassembly_gc_uninitialized_object_field_traps(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        execute(
            tmp_path,
            """
class Value:
    def __init__(self, number: int):
        self.number = number


class Holder:
    def __init__(self, value: Value, initialize: bool):
        if initialize:
            self.value = value


def main() -> int:
    return Holder(Value(1), False).value.number
""",
        )


def test_webassembly_gc_slice_rejects_static_methods():
    with pytest.raises(WebAssemblyUnsupported, match="static and class methods"):
        transpile_webassembly(
            """
class Value:
    @staticmethod
    def answer() -> int:
        return 42


def main() -> int:
    return Value.answer()
"""
        )


@pytest.mark.parametrize("expression", ["1 and 2", "0 or 3"])
def test_webassembly_boolops_reject_non_boolean_results(expression):
    with pytest.raises(WebAssemblyUnsupported, match="require bool operands"):
        transpile_webassembly(f"def main() -> int:\n    return {expression}\n")
