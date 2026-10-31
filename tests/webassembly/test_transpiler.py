import asyncio
import base64
import json
import shutil
import subprocess
import sys

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.tooling.browser import Browser
from pyjs.webassembly import (
    WebAssemblyUnsupported,
    grow_memory,
    load_f32,
    load_f64,
    load_i32,
    memory_byte_length,
    reset_memory,
    store_f32,
    store_f64,
    store_i32,
    transpile_webassembly,
)
from tests.backend_semantics import (
    APPLICATION_GENERIC_UNION_ORDER_CONTRACT,
    ASSERT_NARROWING_CONTRACT,
    BACKEND_CONTRACTS,
    BINARY_POWER_CONTRACT,
    BOOLEAN_NUMERIC_CONTRACT,
    CALLABLE_INPUT_CONTRACT,
    CHAINED_COMPARISON_CONTRACT,
    CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT,
    COLLECTION_NAME_CONTRACT,
    CUSTOM_EXCEPTION_CONTRACT,
    DATACLASS_NAN_IDENTITY_SOURCE,
    DIRECT_UNION_RESULT_CONTRACT,
    DOCUMENT_COLLECTION_CONTRACT,
    EXCEPTION_OBJECT_CONTRACT,
    FIELD_ASSIGNMENT_CONTRACT,
    FIXED_TUPLE_ASSIGNMENT_CONTRACT,
    GENERATOR_CLEANUP_CONTRACT,
    GENERIC_OPERATOR_CONTRACT,
    GENERIC_UNION_ORDER_CONTRACT,
    INHERITED_FACTORY_FIELD_CONTRACT,
    INHERITED_FIELD_ASSIGNMENT_CONTRACT,
    INTEGER_LIST_MEMBERSHIP_CONTRACT,
    KEYWORD_ARGUMENT_CONTRACT,
    LITERAL_FIELD_ASSIGNMENT_CONTRACT,
    LITERAL_SEQUENCE_REFLECTION_CONTRACT,
    MAPPING_LOOKUP_REPRESENTATION_CONTRACT,
    MIXED_TRUTH_CONDITION_CONTRACT,
    NESTED_CONDITIONAL_CONTRACT,
    NUMERIC_NAME_CONTRACT,
    PORTABLE_FAILURE_SOURCES,
    POSTPONED_DATACLASS_CONTRACT,
    PROPERTY_FIELD_OVERRIDE_CONTRACT,
    PROPERTY_GETTER_CONTRACT,
    RANGE_LOOP_CONTRACT,
    RANGE_NUMERIC_LOOKUP_CONTRACT,
    RECURSIVE_EQUALITY_CONTRACT,
    RECURSIVE_OPTIONAL_CONTRACT,
    RECURSIVE_TREE_CONTRACT,
    REVERSED_PROTOCOL_CONTRACT,
    SCALAR_MAPPING_VALUES_CONTRACT,
    SEQUENCE_REFLECTION_CONTRACT,
    STRING_DICTIONARY_MEMBERSHIP_CONTRACT,
    STRING_LIST_MEMBERSHIP_CONTRACT,
    STRUCTURAL_OPERATOR_CONTRACT,
    TEXT_SERIALIZATION_CONTRACT,
    UNICODE_CHARACTER_CONTRACT,
    UNION_KEY_REPRESENTATION_CONTRACT,
    UNPACK_FIELD_CONTRACT,
    nominal_object_contract,
)


def test_literal_strings_keep_explicit_wasm_boundary():
    from tests.backend_semantics import LITERAL_STRING_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly value type str is not implemented$"):
        transpile_webassembly(LITERAL_STRING_CONTRACT.source)


def test_dictionary_iteration_keeps_explicit_wasm_boundary():
    from tests.backend_semantics import DICTIONARY_KEYS_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly value type dict__str_int is not implemented$"):
        transpile_webassembly(DICTIONARY_KEYS_CONTRACT.source)


def test_dictionary_pop_keeps_explicit_wasm_boundary():
    from tests.backend_semantics import DICTIONARY_POP_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly value type dict__str_int is not implemented$"):
        transpile_webassembly(DICTIONARY_POP_CONTRACT.source)


def test_local_collections_keep_explicit_wasm_boundary():
    from tests.backend_semantics import LOCAL_COLLECTION_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly value type str is not implemented$"):
        transpile_webassembly(LOCAL_COLLECTION_CONTRACT.source)


def test_narrowed_receiver_contract_keeps_wasm_inheritance_boundary():
    from tests.backend_semantics import NARROWED_METHOD_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly class inheritance is not implemented$"):
        transpile_webassembly(NARROWED_METHOD_CONTRACT.source)


def test_replaced_attribute_contract_keeps_wasm_inheritance_boundary():
    from tests.backend_semantics import REPLACED_ATTRIBUTE_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly class inheritance is not implemented$"):
        transpile_webassembly(REPLACED_ATTRIBUTE_CONTRACT.source)


@pytest.mark.parametrize("case", ["local_method", "local_property", "field_store"])
def test_replaced_receiver_keeps_wasm_inheritance_boundary(case):
    from tests.backend_semantics import REPLACED_RECEIVER_CONTRACTS

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly class inheritance is not implemented$"):
        transpile_webassembly(REPLACED_RECEIVER_CONTRACTS[case].source)


def test_explicit_split_keeps_wasm_string_boundary():
    from tests.backend_semantics import EXPLICIT_SPLIT_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly value type str is not implemented$"):
        transpile_webassembly(EXPLICIT_SPLIT_CONTRACT.source)


def test_receiver_domain_keeps_wasm_inheritance_boundary():
    from tests.backend_semantics import RECEIVER_DOMAIN_CONTRACTS

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly class inheritance is not implemented$"):
        transpile_webassembly(RECEIVER_DOMAIN_CONTRACTS["default"].source)


def test_shared_list_truth_contract(tmp_path):
    from tests.backend_semantics import LIST_TRUTH_CONTRACT

    result = int(execute(tmp_path, LIST_TRUTH_CONTRACT.source))
    assert result == 0, LIST_TRUTH_CONTRACT.failure(result)


def test_awaited_attribute_contract_keeps_wasm_string_boundary():
    from tests.backend_semantics import AWAIT_ATTRIBUTE_SOURCE

    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly value type str is not implemented$"):
        transpile_webassembly(AWAIT_ATTRIBUTE_SOURCE + '''
async def main() -> str:
    return await await_attributes()
''')


def test_optional_float_contract_keeps_explicit_wasm_boundary():
    from tests.backend_semantics import OPTIONAL_FLOAT_CONTRACT

    with pytest.raises(WebAssemblyUnsupported, match="union value storage"):
        transpile_webassembly(OPTIONAL_FLOAT_CONTRACT.source)


@pytest.mark.parametrize("name", ["cast", "cast as project"])
def test_typing_cast_reaches_explicit_wasm_boundary(name):
    call = "project" if " as " in name else name
    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly expression StaticCast is not implemented at line 3$"):
        transpile_webassembly(f"from typing import {name}\ndef main() -> int:\n    value = 3\n    return {call}(int, value)\n")


def test_keyword_only_calls_keep_explicit_wasm_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly functions require fixed positional parameters$"):
        transpile_webassembly(KEYWORD_ARGUMENT_CONTRACT.source)


def test_chained_comparisons_keep_explicit_wasm_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly expression ChainedCompare is not implemented"):
        transpile_webassembly(CHAINED_COMPARISON_CONTRACT.source)


def test_unicode_characters_keep_explicit_wasm_string_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly value type str is not implemented$"):
        transpile_webassembly(UNICODE_CHARACTER_CONTRACT.source)


def test_boolean_arithmetic_has_an_explicit_wasm_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly call target __add__ is not implemented"):
        transpile_webassembly(BOOLEAN_NUMERIC_CONTRACT.source)


def test_property_getter_contract_keeps_wasm_inheritance_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly class inheritance is not implemented$"):
        transpile_webassembly(PROPERTY_GETTER_CONTRACT.source)


@pytest.mark.parametrize(("contract", "message"), [
    (INTEGER_LIST_MEMBERSHIP_CONTRACT, "WebAssembly call target __contains__ is not implemented"),
    (STRING_DICTIONARY_MEMBERSHIP_CONTRACT, "WebAssembly value type dict__str_str is not implemented"),
    (STRING_LIST_MEMBERSHIP_CONTRACT, "WebAssembly value type str is not implemented"),
])
def test_membership_contract_has_an_explicit_wasm_boundary(contract, message):
    with pytest.raises(WebAssemblyUnsupported) as error:
        transpile_webassembly(contract.source)
    assert str(error.value) == message


@pytest.mark.parametrize(("contract", "message"), [
    (SCALAR_MAPPING_VALUES_CONTRACT, "WebAssembly value type dict__str_int is not implemented"),
    (TEXT_SERIALIZATION_CONTRACT, "WebAssembly value type str is not implemented"),
])
def test_serialization_primitives_keep_explicit_wasm_boundaries(contract, message):
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


def test_fixed_tuple_assignment_reaches_the_wasm_string_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type str is not implemented"):
        transpile_webassembly(FIXED_TUPLE_ASSIGNMENT_CONTRACT.source)


def test_list_copy_contract_keeps_the_wasm_identity_boundary():
    from tests.backend_semantics import LIST_COPY_CONTRACT
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly(LIST_COPY_CONTRACT.source)
    assert str(caught.value) == (
        "WebAssembly call target __is__ is not implemented at line 18"
    )


def test_shared_range_loop_contract(tmp_path):
    result = int(execute(tmp_path, RANGE_LOOP_CONTRACT.source))
    assert result == 0, RANGE_LOOP_CONTRACT.failure(result)


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
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly numeric conversion is not implemented"):
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
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly call target unpack_exact is not implemented"):
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


def test_literal_tuple_instance_contract_keeps_wasm_single_target_boundary():
    from tests.backend_semantics import ISINSTANCE_LITERAL_TUPLE_CONTRACT
    with pytest.raises(CompilationError, match="to isinstance expects type"):
        transpile_webassembly(ISINSTANCE_LITERAL_TUPLE_CONTRACT.source)


def test_shared_positional_minmax_contract(tmp_path):
    from tests.backend_semantics import POSITIONAL_MINMAX_CONTRACT
    result = int(execute(tmp_path, POSITIONAL_MINMAX_CONTRACT.source))
    assert result == 0, POSITIONAL_MINMAX_CONTRACT.failure(result)


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


def test_mapping_lookup_contract_has_explicit_mapping_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type dict__str_tuple__int_list__float is not implemented"):
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


def test_explicit_variadic_tuple_constructor_has_a_webassembly_capability_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type tuple__int__variadic is not implemented"):
        transpile_webassembly('''from pyjs import int8
def main() -> int:
    source = [int8(127)]
    copied = tuple[int8, ...](source)
    return int(copied[0] + 1)
''')


def test_explicit_list_constructor_keeps_fixed_width_items(tmp_path):
    result = execute(tmp_path, '''from pyjs import int8
def main() -> int:
    source = [int8(127)]
    copied = list[int8](source)
    return int(copied[0] + 1)
''')

    assert result == "-128"


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


def test_document_collections_keep_explicit_string_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly value type str is not implemented"):
        transpile_webassembly(DOCUMENT_COLLECTION_CONTRACT.source)


def test_webassembly_property_override_keeps_unsupported_analysis_boundary():
    with pytest.raises(CompilationError, match="Function returns str.*NoneType, not str"):
        transpile_webassembly(PROPERTY_FIELD_OVERRIDE_CONTRACT.source)


def test_webassembly_nested_conditional_order(tmp_path):
    contract = NESTED_CONDITIONAL_CONTRACT
    result = int(execute(tmp_path, contract.source))
    assert result == 0, contract.failure(result)


def test_webassembly_mixed_truth_condition_storage_boundary():
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly(MIXED_TRUTH_CONDITION_CONTRACT.source)
    assert str(caught.value) == "WebAssembly union value storage is not implemented"


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


def test_linear_memory_reference_runtime_round_trips_and_grows():
    reset_memory()
    store_i32(0, 2**32 - 7)
    store_f32(4, 1.5)
    store_f64(8, 2.25)

    assert load_i32(0) == -7
    assert load_f32(4) == 1.5
    assert load_f64(8) == 2.25
    assert grow_memory(1) == 1
    assert memory_byte_length() == 2 * 65_536
    assert load_f64(8) == 2.25

    with pytest.raises(IndexError):
        store_f64(-1, 0.0)
    with pytest.raises(IndexError):
        load_i32(memory_byte_length() - 3)


def test_webassembly_exports_persistent_linear_memory_only_when_reached(tmp_path):
    source = """
from pyjs.webassembly import grow_memory, store_f32, store_f64, store_i32


def main(value: float) -> int:
    if value < 0.0:
        return grow_memory(1)
    store_i32(0, -7)
    store_f32(4, 1.5)
    store_f64(8, value)
    return 16
"""
    path = transpile_webassembly(source).write(tmp_path / "memory.wasm")
    plain_path = transpile_webassembly(
        "def main() -> int:\n    return 1\n"
    ).write(tmp_path / "plain.wasm")
    script = """
const fs = require('fs');
const memoryPath = process.argv[1];
const plainPath = process.argv[2];
Promise.all([
    WebAssembly.instantiate(fs.readFileSync(memoryPath)),
    WebAssembly.instantiate(fs.readFileSync(plainPath)),
]).then(([withMemory, plain]) => {
    const {exports} = withMemory.instance;
    if (exports.main(2.25) !== 16n) throw new Error('descriptor');
    let view = new DataView(exports.memory.buffer);
    if (view.getInt32(0, true) !== -7) throw new Error('i32');
    if (view.getFloat32(4, true) !== 1.5) throw new Error('f32');
    if (view.getFloat64(8, true) !== 2.25) throw new Error('f64');
    if (exports.main(-1.0) !== 1n) throw new Error('grow result');
    if (exports.memory.buffer.byteLength !== 131072) throw new Error('grow');
    view = new DataView(exports.memory.buffer);
    if (view.getFloat64(8, true) !== 2.25) throw new Error('persistence');
    if ('memory' in plain.instance.exports) throw new Error('unused memory');
    console.log('ok');
}).catch(error => { console.error(error); process.exit(1); });
"""

    result = subprocess.run(
        [node(), "-e", script, str(path), str(plain_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "ok"


def test_webassembly_exports_multiple_functions_with_shared_memory(tmp_path):
    source = """
from pyjs.webassembly import load_i32, store_i32


def initialize(value: int) -> int:
    store_i32(0, value)
    return load_i32(0)


def increment(delta: int) -> int:
    value = load_i32(0) + delta
    store_i32(0, value)
    return load_i32(0)


def read() -> int:
    return load_i32(0)
"""
    module = transpile_webassembly(
        source,
        exports=("initialize", "increment", "read"),
    )
    path = module.write(tmp_path / "multi-export.wasm")
    script = """
const fs = require('fs');
WebAssembly.instantiate(fs.readFileSync(process.argv[1])).then(({instance}) => {
    const {exports} = instance;
    if (exports.initialize(40n) !== 40n) throw new Error('initialize');
    if (exports.increment(2n) !== 42n) throw new Error('increment');
    if (exports.read() !== 42n) throw new Error('read');
    if (exports.memory.buffer.byteLength !== 65536) throw new Error('memory');
    if ('main' in exports) throw new Error('unexpected main');
    console.log('ok');
}).catch(error => { console.error(error); process.exit(1); });
"""

    result = subprocess.run(
        [node(), "-e", script, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize(
    ("exports", "message"),
    [
        ((), "at least one"),
        (("main", "main"), "unique"),
        (("memory",), "cannot be named memory"),
    ],
)
def test_webassembly_rejects_invalid_export_sets(exports, message):
    with pytest.raises(ValueError, match=message):
        transpile_webassembly("def main() -> int:\n    return 1\n", exports=exports)


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


def test_webassembly_executes_an_imported_helper_with_a_client_constant(
    tmp_path,
    monkeypatch,
):
    module_name = "pyjs_webassembly_imported_constant"
    (tmp_path / f"{module_name}.py").write_text(
        "from typing import Final\n\n"
        "from pyjs import JS\n\n"
        "INCREMENT: Final[JS] = 2\n\n"
        "def increment(value: int) -> int:\n"
        "    return value + INCREMENT\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(module_name, None)

    result = execute(
        tmp_path,
        f"""
from {module_name} import increment


def main() -> int:
    return increment(40)
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (1, "1"), (-1, "1"), (-2, "0")],
)
def test_webassembly_boolean_operators_short_circuit(tmp_path, value, expected):
    source = """
def main(value: int) -> bool:
    positive = value > 0 and 10 // value > 1
    non_positive = not positive
    return positive or (non_positive and value == -1)
"""

    assert execute(tmp_path, source, f"{value}n") == expected


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


def test_webassembly_gc_tuples_execute_literals_parameters_and_indexing(tmp_path):
    result = execute(
        tmp_path,
        """
def total(values: tuple[int, float, int]) -> float:
    return values[0] + values[1] + values[-1] + len(values)


def main() -> float:
    return total((1, 2.5, 3))
""",
    )

    assert result == "9.5"


def test_webassembly_gc_tuples_support_nested_destructuring(tmp_path):
    result = execute(
        tmp_path,
        """
def pair() -> tuple[tuple[int, float], int]:
    return ((1, 2.5), 3)


def main() -> float:
    (left, middle), right = pair()
    return left + middle + right
""",
    )

    assert result == "6.5"


def test_webassembly_gc_tuple_list_iteration_supports_destructuring(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> float:
    values: list[tuple[int, float]] = [(1, 2.5), (3, 4.5)]
    total = 0.0
    for integer, floating in values:
        total += integer + floating
    return total
""",
    )

    assert result == "11"


def test_webassembly_gc_tuple_fields_hold_application_objects(tmp_path):
    result = execute(
        tmp_path,
        """
class Point:
    def __init__(self, x: float):
        self.x = x


class Segment:
    def __init__(self, endpoints: tuple[Point, Point]):
        self.endpoints = endpoints

    def length(self) -> float:
        return self.endpoints[1].x - self.endpoints[0].x


def main() -> float:
    return Segment((Point(1.5), Point(4.0))).length()
""",
    )

    assert result == "2.5"


def test_webassembly_range_supports_positive_and_negative_steps(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> int:
    total = 0
    for value in range(5):
        total += value
    for value in range(8, 3, -2):
        total += value
    for value in range(2, 5):
        total += value
    for value in range(1, 5, -1):
        total += 100
    return total
""",
    )

    assert result == "37"


def test_webassembly_range_stops_before_signed_overflow(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> int:
    count = 0
    for value in range(9223372036854775806, 9223372036854775807, 2):
        count += 1
    for value in range(-9223372036854775807, -9223372036854775808, -2):
        count += 1
    return count
""",
    )

    assert result == "2"


def test_webassembly_range_zero_step_traps(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        execute(
            tmp_path,
            """
def main() -> int:
    total = 0
    for value in range(0, 3, 0):
        total += value
    return total
""",
        )


def test_webassembly_enumerate_and_zip_compose_iterators(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> int:
    total = 0
    for index, pair in enumerate(zip([1, 2], range(3, 5)), start=1):
        total += index * (pair[0] + pair[1])
    return total
""",
    )

    assert result == "16"


def test_webassembly_enumerate_preserves_fixed_width_list_items(tmp_path):
    result = execute(
        tmp_path,
        """
from pyjs import int8


def main() -> int:
    values: list[int8] = [int8(2), int8(3)]
    total = 0
    for index, value in enumerate(values, 4):
        total += index * int(value)
    return total
""",
    )

    assert result == "23"


def test_webassembly_enumerate_traps_before_index_overflow(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        execute(
            tmp_path,
            """
def main() -> int:
    total = 0
    for index, value in enumerate([1, 2], 9223372036854775807):
        total += index * value
    return total
""",
        )


def test_webassembly_zip_stops_at_shortest_input(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> int:
    total = 0
    for left, right in zip([1, 2], [3]):
        total += left * right
    return total
""",
    )

    assert result == "3"


def test_webassembly_strict_zip_traps_on_different_lengths(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        execute(
            tmp_path,
            """
def main() -> int:
    total = 0
    for left, right in zip([1, 2], [3], strict=True):
        total += left * right
    return total
""",
        )


def test_webassembly_numeric_intrinsics_execute_python_values(tmp_path):
    result = execute(
        tmp_path,
        """
from math import hypot, sqrt


def main() -> float:
    small = min(4.0, 2.0, 3.0)
    large = max(4.0, 2.0, 3.0)
    return sqrt(9.0) + hypot(3e200, 4e200) / 1e200 + small + large
""",
    )

    assert result == "14"


def test_webassembly_trigonometry_uses_explicit_math_imports(tmp_path):
    module = transpile_webassembly(
        """
from math import cos, radians, sin


def main() -> float:
    return sin(radians(30.0)) + cos(radians(60.0))
"""
    )
    path = module.write(tmp_path / "trigonometry.wasm")
    script = """
const fs = require('fs');
WebAssembly.compile(fs.readFileSync(process.argv[1])).then(module => {
    const imports = WebAssembly.Module.imports(module);
    return WebAssembly.instantiate(module, {
        math: {sin: Math.sin, cos: Math.cos},
    }).then(instance => {
        console.log(JSON.stringify([
            imports.map(value => [value.module, value.name, value.kind]),
            instance.exports.main(),
        ]));
    });
}).catch(error => {console.error(error); process.exit(1)});
"""
    result = subprocess.run(
        [node(), "-e", script, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )

    imports, value = json.loads(result.stdout)
    assert imports == [
        ["math", "sin", "function"],
        ["math", "cos", "function"],
    ]
    assert value == pytest.approx(1.0)


def test_webassembly_hypot_prefers_infinity_and_preserves_nan(tmp_path):
    source = """
from math import hypot


def main(left: float, right: float) -> float:
    return hypot(left, right)
"""

    assert execute(tmp_path, source, "Infinity, NaN") == "Infinity"
    assert execute(tmp_path, source, "NaN, 0.0") == "NaN"


def test_webassembly_extrema_evaluate_arguments_once(tmp_path):
    result = execute(
        tmp_path,
        """
class Values:
    def __init__(self):
        self.reads = 0

    def take(self, value: int) -> int:
        self.reads += 1
        return value


def main() -> int:
    values = Values()
    selected = min(values.take(4), values.take(2), values.take(3))
    return selected * 10 + values.reads
""",
    )

    assert result == "23"


def test_webassembly_sqrt_negative_value_traps(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        execute(
            tmp_path,
            """
from math import sqrt


def main() -> float:
    return sqrt(-1.0)
""",
        )


def test_webassembly_list_copy_concat_and_truthiness_are_independent(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> float:
    source = [1.0, 2.0]
    copied = list(source)
    combined = source + [3.0]
    copied[0] = 4.0
    combined[1] = 5.0
    empty: list[float] = []
    if empty:
        return -1.0
    if not copied:
        return -1.0
    return source[0] * 100.0 + copied[0] * 10.0 + combined[1] + combined[2]
""",
    )

    assert result == "148"


def test_webassembly_list_comprehensions_scope_filter_and_unpack(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> int:
    value = 10
    products = [
        left * right
        for left, right in zip(range(1, 7), range(2, 8))
        if left > 2
    ]
    grid = [[row * 10 + column for column in range(3)] for row in range(2)]
    return value + products[0] + products[-1] + len(products) + grid[1][2]
""",
    )

    assert result == "80"


def test_webassembly_list_comprehensions_preserve_fixed_width_items(tmp_path):
    result = execute(
        tmp_path,
        """
from pyjs import int8


def main() -> int8:
    values = [int8(index * 100) for index in range(3)]
    return values[2]
""",
    )

    assert result == "-56"


def test_webassembly_nullable_gc_results_narrow_after_identity_checks(tmp_path):
    source = """
def choose(flag: bool) -> list[float] | None:
    return [1.5, 2.5] if flag else None


def main(flag: bool) -> float:
    result = choose(flag)
    if result is None:
        return -1.0
    return result[0] + result[1]
"""

    assert execute(tmp_path, source, "1") == "4"
    assert execute(tmp_path, source, "0") == "-1"


def test_webassembly_nullable_gc_fields_hold_application_objects(tmp_path):
    result = execute(
        tmp_path,
        """
class Node:
    def __init__(self, value: int, next_node: Node | None):
        self.value = value
        self.next_node = next_node


def main() -> int:
    tail = Node(2, None)
    head = Node(1, tail)
    if head.next_node is None:
        return -1
    if tail.next_node is not None:
        return -2
    return head.value * 10 + head.next_node.value
""",
    )

    assert result == "12"


def test_webassembly_simultaneous_index_assignment_evaluates_rhs_first(tmp_path):
    result = execute(
        tmp_path,
        """
def main() -> float:
    values = [[1.0], [2.0]]
    left = 0
    right = 1
    values[left], values[right] = values[right], values[left]
    return values[0][0] * 10.0 + values[1][0]
""",
    )

    assert result == "21"


@pytest.mark.parametrize(("name", "expected"), [("range", "7"), ("zip", "7"), ("enumerate", "7")])
def test_application_functions_named_like_iterators_stay_ordinary_calls(tmp_path, name, expected):
    result = execute(tmp_path, f"""
def {name}(value: int) -> list[int]:
    return [value]


def main() -> int:
    total = 0
    for value in {name}(7):
        total += value
    return total
""")

    assert result == expected


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
