import gc
import weakref
from typing import Annotated, NotRequired, ReadOnly, Required

import pytest

import pyjs
import tests.backend_semantics as backend_semantics
from pyjs import (
    StaticArray,
    float32,
    float64,
    int8,
    int16,
    int32,
    int64,
    uint8,
    uint16,
    uint32,
)
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.java import f32, f64, i32
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.numeric import (
    ArrayFormat,
    NumericFormat,
    array_format,
    array_item,
    numeric_format,
)
from pyjs.shader import Array as ShaderArray
from pyjs.shader import f32 as shader_f32
from pyjs.shader import i32 as shader_i32
from pyjs.shader import u32 as shader_u32
from pyjs.testing.helpers import (
    assert_diagnostic,
    assert_module_analysis_transpile,
    assert_module_transpile,
    diagnostic_text,
)
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import (
    BACKEND_CONTRACTS,
    BINARY_POWER_CONTRACT,
    BOOLEAN_NUMERIC_CONTRACT,
    MODULAR_POWER_CONTRACT,
    PORTABLE_FAILURE_SOURCES,
    RANGE_LOOP_CONTRACT,
    RANGE_NUMERIC_LOOKUP_CONTRACT,
)
from tests.semantics.helpers import RuntimeResult, assert_semantics, run_javascript


@pytest.mark.parametrize(
    ("annotation", "expected"),
    (
        (int8, NumericFormat("integer", 8, True)),
        (uint8, NumericFormat("integer", 8, False)),
        (int16, NumericFormat("integer", 16, True)),
        (uint16, NumericFormat("integer", 16, False)),
        (int32, NumericFormat("integer", 32, True)),
        (uint32, NumericFormat("integer", 32, False)),
        (int64, NumericFormat("integer", 64, True)),
        (float32, NumericFormat("float", 32)),
        (float64, NumericFormat("float", 64)),
    ),
)
def test_shared_numeric_annotations_preserve_python_values(annotation, expected):
    value = annotation(3)

    assert value == 3
    assert type(value) is annotation
    assert numeric_format(annotation) == expected


def test_static_array_metadata_survives_standard_annotation_wrappers():
    annotation = Annotated[StaticArray[int8, 2], "metadata"]

    assert array_format(annotation) == ArrayFormat(
        2,
        item_numeric=NumericFormat("integer", 8, True),
    )
    assert array_item(annotation) is int8


@pytest.mark.parametrize("wrapper", (NotRequired, ReadOnly, Required))
def test_numeric_metadata_survives_typed_dict_annotation_wrappers(wrapper):
    assert numeric_format(wrapper[int8]) == NumericFormat("integer", 8, True)


@pytest.mark.parametrize("wrapper", (NotRequired, ReadOnly, Required))
def test_static_array_metadata_survives_typed_dict_annotation_wrappers(wrapper):
    annotation = wrapper[StaticArray[int8, 2]]

    assert array_format(annotation) == ArrayFormat(
        2,
        item_numeric=NumericFormat("integer", 8, True),
    )
    assert array_item(annotation) is int8


@pytest.mark.parametrize(
    "contract",
    [*BACKEND_CONTRACTS.values(), RANGE_LOOP_CONTRACT, BOOLEAN_NUMERIC_CONTRACT, RANGE_NUMERIC_LOOKUP_CONTRACT,
     BINARY_POWER_CONTRACT, MODULAR_POWER_CONTRACT],
    ids=[*BACKEND_CONTRACTS, "range loop", "Boolean numerics", "Range numeric lookup", "Binary power", "Modular power"],
)
def test_shared_numeric_contract_runs_under_cpython(contract):
    namespace = {}
    exec(contract.source, namespace)
    result = namespace["main"]()

    assert result == 0, contract.failure(result)


def test_backend_contracts_cannot_wrap_process_exit_codes():
    checks = tuple((f"check {index}", "False") for index in range(256))

    with pytest.raises(
        ValueError,
        match="backend contracts cannot exceed 255 checks",
    ):
        backend_semantics._contract("", "oversized", "", checks)


def test_portable_backend_layout_matrix_covers_each_integer_type_once():
    assert backend_semantics.PORTABLE_INTEGER_LAYOUTS == (
        ("int8", 8, True),
        ("uint8", 8, False),
        ("int16", 16, True),
        ("uint16", 16, False),
        ("int32", 32, True),
        ("uint32", 32, False),
        ("int64", 64, True),
    )


@pytest.mark.parametrize(
    ("operator", "operation"),
    (
        ("//", lambda left, right: left // right),
        ("%", lambda left, right: left % right),
        ("**", lambda left, right: left**right),
        ("divmod()", divmod),
    ),
)
def test_portable_float_rejects_operations_without_a_shared_contract(
    operator,
    operation,
):
    with pytest.raises(TypeError) as caught:
        operation(float32(4.0), float32(2.0))

    assert str(caught.value) == (
        f"portable fixed-width floats do not support {operator}"
    )


@pytest.mark.parametrize(
    ("method", "other", "operator"),
    (
        ("__floordiv__", float32(2.0), "//"),
        ("__rfloordiv__", float32(2.0), "//"),
        ("__mod__", float32(2.0), "%"),
        ("__rmod__", float32(2.0), "%"),
        ("__divmod__", float32(2.0), "divmod()"),
        ("__rdivmod__", float32(2.0), "divmod()"),
    ),
)
def test_portable_float_dunders_follow_unsupported_operation_contract(
    method,
    other,
    operator,
):
    with pytest.raises(TypeError) as caught:
        getattr(float32(5.0), method)(other)

    assert str(caught.value) == (
        f"portable fixed-width floats do not support {operator}"
    )


@pytest.mark.parametrize("annotation", (float32, float64))
def test_portable_float_round_preserves_type_with_ndigits(annotation):
    rounded = round(annotation(1.2345), 3)

    assert type(rounded) is annotation
    assert rounded == annotation(round(float(annotation(1.2345)), 3))
    assert type(round(annotation(1.5))) is int


def test_static_array_length_and_item_format_are_part_of_its_type():
    annotation = StaticArray[int16, 3]
    values = annotation([int16(1), int16(2), int16(3)])

    assert values == [1, 2, 3]
    assert type(values) is annotation
    assert array_format(annotation) == ArrayFormat(
        3,
        item_numeric=NumericFormat("integer", 16, True),
    )


def test_unused_static_array_specializations_can_be_collected():
    def references():
        class Item:
            pass

        annotation = StaticArray[Item, 1]
        assert StaticArray[Item, 1] is annotation
        return weakref.ref(Item), weakref.ref(annotation)

    item, annotation = references()
    gc.collect()

    assert annotation() is None
    gc.collect()
    assert item() is None


def test_nested_static_arrays_preserve_their_complete_layout():
    row = StaticArray[float32, 2]
    matrix = StaticArray[row, 3]

    assert array_format(matrix) == ArrayFormat(
        3,
        item_array=ArrayFormat(
            2,
            item_numeric=NumericFormat("float", 32),
        ),
    )


def test_shader_array_is_a_distinct_array_domain():
    annotation = ShaderArray[shader_i32, 4]

    assert array_format(annotation) == ArrayFormat(
        4,
        domain="wgsl",
        item_numeric=NumericFormat("integer", 32, True, domain="wgsl"),
    )


def test_static_array_layout_rejects_mixed_numeric_domains():
    with pytest.raises(TypeError, match="stored item must use the same domain"):
        array_format(StaticArray[shader_i32, 2])

    with pytest.raises(TypeError, match="stored item must use the same domain"):
        array_format(ShaderArray[int32, 2])


def test_static_array_validates_construction_and_prevents_resizing():
    annotation = StaticArray[int, 2]
    values = annotation([1, 2])

    with pytest.raises(ValueError, match="requires 2 items, got 1"):
        annotation([1])
    with pytest.raises(TypeError, match="cannot change length"):
        values.append(3)
    with pytest.raises(TypeError, match="cannot change length"):
        values[0:1] = [3, 4]

    values[0] = 3
    values[:] = [4, 5]
    assert values == [4, 5]


def test_static_array_coerces_fixed_items_and_rejects_implicit_conversions():
    type Sample = int8

    values = StaticArray[Sample, 2]([130, 2])

    assert values == [-126, 2]
    values[1] = 129
    assert values == [-126, -127]
    with pytest.raises(TypeError, match="requires an explicit conversion"):
        values[0] = int16(1)


def test_numeric_metadata_accepts_external_domains_but_not_bool_storage():
    assert NumericFormat("integer", 32, True, domain="swift").domain == "swift"
    assert ArrayFormat(2, domain="clr").domain == "clr"
    with pytest.raises(TypeError, match="integer numeric formats require int"):
        numeric_format(Annotated[bool, NumericFormat("integer", 8, True)])
    with pytest.raises(TypeError, match="unsupported numeric domain"):
        NumericFormat("integer", 32, True, domain="swift.numeric")
    with pytest.raises(TypeError, match="require signedness"):
        NumericFormat("integer", 32, 1)
    with pytest.raises(TypeError, match="unsupported numeric domain"):
        NumericFormat("integer", 32, True, domain=1)
    with pytest.raises(TypeError, match="unsupported numeric format kind"):
        NumericFormat([], 32, True)
    with pytest.raises(TypeError, match="do not support 8.0 bits"):
        NumericFormat("integer", 8.0, True)


@pytest.mark.parametrize("length", (True, 2.0, "2", 0, -1))
def test_array_metadata_requires_a_positive_integer_length(length):
    with pytest.raises(TypeError, match="positive integer"):
        ArrayFormat(length)


@pytest.mark.parametrize(
    ("arguments", "message"),
    (
        ({"domain": 1}, "unsupported array domain"),
        ({"item_numeric": "int8"}, "requires NumericFormat"),
        ({"item_array": "nested"}, "requires ArrayFormat"),
    ),
)
def test_array_metadata_rejects_malformed_layout_values(arguments, message):
    with pytest.raises(TypeError, match=message):
        ArrayFormat(1, **arguments)


@pytest.mark.parametrize(
    ("bits", "signed", "expected"),
    (
        (8, True, (-128, 127)),
        (8, False, (0, 255)),
        (16, True, (-32768, 32767)),
        (16, False, (0, 65535)),
        (32, True, (-(2**31), 2**31 - 1)),
        (32, False, (0, 2**32 - 1)),
        (64, True, (-(2**63), 2**63 - 1)),
    ),
)
def test_integer_numeric_formats_expose_their_inclusive_bounds(
    bits,
    signed,
    expected,
):
    assert NumericFormat("integer", bits, signed).integer_bounds == expected


def test_float_numeric_formats_do_not_expose_integer_bounds():
    with pytest.raises(TypeError, match="do not have integer bounds"):
        _ = NumericFormat("float", 32).integer_bounds


@pytest.mark.parametrize(
    "annotation",
    (
        lambda: StaticArray[int],
        lambda: StaticArray[int, 0],
        lambda: StaticArray[int, -1],
        lambda: StaticArray[int, "2"],
    ),
)
def test_static_array_requires_one_positive_literal_length(annotation):
    with pytest.raises(TypeError):
        annotation()


@pytest.mark.parametrize(
    ("numeric_type", "minimum", "maximum"),
    (
        (int8, -(2**7), 2**7 - 1),
        (uint8, 0, 2**8 - 1),
        (int16, -(2**15), 2**15 - 1),
        (uint16, 0, 2**16 - 1),
        (int32, -(2**31), 2**31 - 1),
        (uint32, 0, 2**32 - 1),
        (int64, -(2**63), 2**63 - 1),
    ),
)
def test_fixed_integer_construction_wraps(numeric_type, minimum, maximum):
    width = maximum - minimum + 1

    assert numeric_type(maximum + 1) == minimum
    assert numeric_type(minimum - 1) == maximum
    assert numeric_type(maximum + width + 2) == minimum + 1


def test_fixed_integer_construction_truncates_floats_and_rejects_other_values():
    assert int8(127.9) == 127
    with pytest.raises(ValueError):
        int8(float("nan"))
    with pytest.raises(OverflowError):
        int8(float("inf"))
    with pytest.raises(TypeError, match=r"int8\(\) requires a number"):
        int8("127")


@pytest.mark.parametrize(
    "operation",
    (
        lambda value: value + 1,
        lambda value: 1 + value,
        lambda value: value - -1,
        lambda value: -1 - value,
        lambda value: value * 3,
        lambda value: 3 * value,
        lambda value: value // 2,
        lambda value: value % 3,
        lambda value: value**2,
        lambda value: value << 2,
        lambda value: value >> 1,
        lambda value: value & 0xFF,
        lambda value: value | 0x80,
        lambda value: value ^ 0x55,
        lambda value: -value,
        lambda value: +value,
        lambda value: ~value,
        lambda value: abs(value),
        lambda value: round(value),
    ),
)
def test_fixed_integer_operations_preserve_their_type(operation):
    assert type(operation(int8(100))) is int8


def test_fixed_integer_division_follows_python_result_type():
    assert int8(7) / 2 == 3.5
    assert type(int8(7) / 2) is float


def test_fixed_integer_operations_reject_mixed_widths():
    with pytest.raises(TypeError, match="unsupported operand type"):
        int8(1) + int16(2)
    with pytest.raises(TypeError, match="unsupported operand type"):
        int8(1) / int16(2)
    with pytest.raises(TypeError, match="cannot be compared"):
        _ = int8(1) == int16(1)


def test_fixed_integer_failures_match_python_integer_failures():
    with pytest.raises(ZeroDivisionError):
        int8(1) // 0
    with pytest.raises(ValueError, match="negative shift count"):
        int8(1) << -1
    with pytest.raises(ValueError, match="negative exponent"):
        int8(2) ** -1


@pytest.mark.parametrize(
    "source",
    PORTABLE_FAILURE_SOURCES.values(),
    ids=PORTABLE_FAILURE_SOURCES,
)
def test_portable_failure_contract_runs_under_cpython(source):
    namespace = {}
    exec(source, namespace)

    with pytest.raises((ValueError, ZeroDivisionError)):
        namespace["main"]()


def test_float32_rounds_construction_and_each_operation():
    rounded = float32(16_777_217.0)

    assert rounded == 16_777_216.0
    assert type(rounded + 1.0) is float32
    assert float32(1.0) / 10.0 == float32(0.1)


def test_fixed_float_special_values_match_javascript():
    assert_semantics(
        """
        from pyjs import float32, float64, js

        @js
        def main() -> None:
            overflow = float32(1e50)
            print(overflow)
            print(-overflow)
            print(overflow - overflow)
            print(float32(-0.0))
            print(float32(-0.0) + float32(-0.0))
            print(float32(-1.0) * float32(0.0))
            print(float64(-0.0))

        main()
        """
    )


def test_fixed_floats_reject_implicit_cross_domain_operations():
    with pytest.raises(TypeError, match="unsupported operand type"):
        float32(1.0) + shader_f32(2.0)
    with pytest.raises(TypeError, match="cannot be compared"):
        _ = float32(1.0) == shader_f32(1.0)


def test_shader_scalars_are_distinct_reference_types():
    assert shader_i32 is not int32
    assert shader_u32 is not uint32
    assert shader_f32 is not float32
    assert numeric_format(shader_i32) == NumericFormat("integer", 32, True, domain="wgsl")
    assert numeric_format(shader_f32) == NumericFormat("float", 32, domain="wgsl")
    assert shader_i32(2**31 - 1) + 1 == -(2**31)
    assert shader_u32(2**32 - 1) + 1 == 0
    assert type(shader_f32(1.0) / 10.0) is shader_f32


def test_numeric_metadata_can_be_nested_with_other_annotations():
    annotation = Annotated[int32, "application metadata"]

    assert numeric_format(annotation) == NumericFormat("integer", 32, True)


def test_numeric_metadata_rejects_invalid_or_ambiguous_formats():
    with pytest.raises(TypeError, match="integer numeric formats require signedness"):
        NumericFormat("integer", 8)
    with pytest.raises(
        TypeError,
        match="floating-point numeric formats do not use signedness",
    ):
        NumericFormat("float", 32, True)
    with pytest.raises(TypeError, match="only one format"):
        numeric_format(
            Annotated[
                int,
                NumericFormat("integer", 8, True),
                NumericFormat("integer", 16, True),
            ]
        )
    with pytest.raises(TypeError, match="only one format"):
        numeric_format(
            Annotated[
                int8,
                NumericFormat("integer", 16, True),
            ]
        )
    with pytest.raises(TypeError, match="integer numeric formats require int"):
        numeric_format(Annotated[str, NumericFormat("integer", 8, True)])
    with pytest.raises(TypeError, match="unsupported numeric format kind"):
        NumericFormat("decimal", 32)
    with pytest.raises(TypeError, match="do not support 16 bits"):
        NumericFormat("float", 16)
    with pytest.raises(TypeError, match="unsigned 64-bit"):
        NumericFormat("integer", 64, False)


def test_java_numeric_types_are_distinct_from_portable_types():
    assert i32 is not int32
    assert f32 is not float32
    assert f64 is not float64
    assert numeric_format(i32) == NumericFormat(
        "integer",
        32,
        True,
        domain="java",
    )
    assert numeric_format(f32) == NumericFormat("float", 32, domain="java")
    assert numeric_format(f64) == NumericFormat("float", 64, domain="java")


def test_shared_numeric_names_are_public():
    assert {
        "StaticArray",
        "float32",
        "float64",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
    } <= set(pyjs.__all__)


def test_javascript_treats_shared_numeric_formats_as_python_types():
    assert_module_analysis_transpile(
        """
        from pyjs import float32, int8, js, uint32

        @js
        class Reading:
            value: int8

            def __init__(self, value: int8) -> None:
                self.value = value

        @js
        def normalize(value: uint32) -> float32:
            sample: float32 = value + 0.5
            return sample

        def main() -> float:
            return normalize(uint32(Reading(6).value))
        """,
        """
        class Reading:

            def __init__(value: int) -> None:
                self.value = value

        def normalize(value: int) -> float:
            sample: float = normalize_float32(0.5.[float]__radd__!(value))
            return sample

        def main() -> float:
            return normalize(int(Reading(normalize_int8(6)).value))
        """,
        """
        export class Reading {

            constructor(value) {
                this.value = value;
            }
        }

        export function normalize(value) {
            var sample = Math.fround(value + 0.5);
            return sample;
        }

        export function main() {
            return normalize((new Reading(((6 << 24) >> 24)).value >>> 0));
        }
        """,
    )


def test_javascript_static_arrays_use_readable_array_values():
    assert_module_analysis_transpile(
        """
        from pyjs import StaticArray, int16, js

        type Row = StaticArray[int16, 3]

        @js
        def first(values: Row) -> int16:
            return values[0]

        @js
        def main() -> int16:
            values: Row = [int16(1), int16(2), int16(3)]
            return first(values)
        """,
        """
        def first(values: list__int) -> int:
            return $get_list_item(values, 0)

        def main() -> int:
            values: list[int] = [int(1), int(2), int(3)]
            return first(values)
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function first(values) {
            return $get_list_item(values, 0);
        }

        export function main() {
            var values = [((1 << 16) >> 16), ((2 << 16) >> 16), ((3 << 16) >> 16)];
            return first(values);
        }
        """,
    )


def test_javascript_static_array_writes_normalize_the_item_format():
    assert_module_analysis_transpile(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main(values: StaticArray[int8, 2]) -> int8:
            values[0] = 130
            return values[0]
        """,
        """
        def main(values: list__int) -> int:
            $set_list_item(values, 0, normalize_int8(130))
            return $get_list_item(values, 0)
        """,
        """
        import { set_list_item as $set_list_item, get_list_item as $get_list_item } from './pyjs.python.js';

        export function main(values) {
            $set_list_item(values, 0, ((130 << 24) >> 24));
            return $get_list_item(values, 0);
        }
        """,
    )


def test_javascript_static_array_construction_normalizes_raw_items():
    assert_module_analysis_transpile(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> int8:
            values = StaticArray[int8, 2]([130, 2])
            return values[0] + 127
        """,
        """
        def main() -> int:
            values: list[int] = [normalize_int8(130), normalize_int8(2)]
            return normalize_int8($get_list_item(values, 0).[int]__add__!(127))
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function main() {
            var values = [((130 << 24) >> 24), ((2 << 24) >> 24)];
            return (($get_list_item(values, 0) + 127 << 24) >> 24);
        }
        """,
    )


def test_javascript_nested_static_arrays_normalize_raw_items_recursively():
    assert_module_transpile(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> int8:
            values = StaticArray[StaticArray[int8, 1], 1]([[130]])
            return values[0][0]
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function main() {
            var values = [[((130 << 24) >> 24)]];
            return $get_list_item($get_list_item(values, 0), 0);
        }
        """,
    )


def test_unannotated_reassignment_does_not_become_fixed_width_storage():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def main() -> None:
            value = int8(1)
            value = 130
            print(value + 0)

        main()
        """
    )


def test_inferred_function_returns_preserve_fixed_width_representation():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def identity(value: int8):
            return value

        def main() -> None:
            print(identity(int8(127)) + 1)

        main()
        """
    )


def test_inferred_optional_returns_preserve_fixed_width_representation():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def choose(enabled: bool):
            if enabled:
                return int8(127)
            return None

        @js
        def consume(enabled: bool) -> None:
            value = choose(enabled)
            if value is not None:
                print(value + 1)

        def main() -> None:
            consume(True)
            consume(False)

        main()
        """
    )


def test_inferred_function_returns_preserve_static_array_layout():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def identity(value: StaticArray[int8, 1]):
            return value

        def main() -> None:
            values = identity(StaticArray[int8, 1]([127]))
            print(values[0] + 1)

        main()
        """
    )


def test_optional_annotations_preserve_nested_representations():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def increment(value: int8 | None) -> int8:
            if value is None:
                return int8(0)
            return value + 1

        @js
        def first(values: StaticArray[int8, 1] | None) -> int8:
            if values is None:
                return int8(0)
            return values[0] + 1

        def main() -> None:
            print(increment(int8(127)), increment(None))
            print(first(StaticArray[int8, 1]([127])), first(None))

        main()
        """
    )


def test_callable_annotations_preserve_parameter_and_return_representations():
    assert_semantics(
        """
        from collections.abc import Callable
        from pyjs import StaticArray, int8, js

        @js
        def invoke(callback: Callable[[int8], int8], value: int8) -> int8:
            return callback(value)

        @js
        def first(
            callback: Callable[[], StaticArray[int8, 1]],
        ) -> int8:
            return callback()[0] + 1

        def main() -> None:
            print(invoke(lambda value: value + 1, int8(127)))
            print(first(lambda: StaticArray[int8, 1]([127])))

        main()
        """
    )


@pytest.mark.parametrize("inferred", (False, True))
def test_async_returns_and_await_preserve_representations(inferred):
    annotation = "" if inferred else " -> int8"
    source = f"""
from pyjs import int8, js

@js
async def load(value: int8){annotation}:
    return value + 1

@js
async def main() -> None:
    print((await load(int8(127))) + 1)
"""
    actual, _javascript = run_javascript(source)

    assert actual == RuntimeResult(0, "-127\n", "")


def test_awaitable_annotations_preserve_nested_representations():
    source = """
from collections.abc import Awaitable
from pyjs import int8, js

@js
async def load() -> int8:
    return int8(127)

@js
async def consume(value: Awaitable[int8]) -> int8:
    return (await value) + 1

@js
async def main() -> None:
    print(await consume(load()))
"""
    actual, _javascript = run_javascript(source)

    assert actual == RuntimeResult(0, "-128\n", "")


def test_type_aliases_preserve_nested_representations():
    assert_semantics(
        """
        from collections.abc import Callable
        from pyjs import int8, js

        type Maybe = int8 | None
        type Callback = Callable[[], int8]

        @js
        def choose(value: Maybe, callback: Callback) -> int8:
            if value is None:
                return callback()
            return value + 1

        def main() -> None:
            print(choose(int8(127), lambda: int8(0)))
            print(choose(None, lambda: int8(127)))

        main()
        """
    )


@pytest.mark.parametrize(
    "annotation",
    (
        "int8 | int16",
        "list[int8 | int16]",
        "list[int8] | list[int16]",
    ),
)
def test_indistinguishable_represented_unions_are_rejected(annotation):
    line = f"def consume(value: {annotation}) -> None:"
    marker = annotation
    assert_diagnostic(
        f"""
        from pyjs import int8, int16, js

        @js
        def consume(value: {annotation}) -> None:
            pass
        """,
        diagnostic_text(
            "represented_union.py",
            4,
            line,
            " " * line.index(marker) + "^" * len(marker),
            "pyjs.CompilationError: Union members use indistinguishable "
            "represented types [PYJS1104]",
            "help: Use one represented type at this boundary, or use ordinary "
            "Python values throughout the union.",
        ),
        filename="represented_union.py",
    )


def test_indistinguishable_callable_unions_are_rejected():
    annotation = "Callable[[], int8] | Callable[[], int16]"
    line = f"def consume(value: {annotation}) -> None:"
    assert_diagnostic(
        f"""
        from collections.abc import Callable
        from pyjs import int8, int16, js

        @js
        def consume(value: {annotation}) -> None:
            pass
        """,
        diagnostic_text(
            "callable_union.py",
            5,
            line,
            " " * line.index(annotation) + "^" * len(annotation),
            "pyjs.CompilationError: Union members use indistinguishable "
            "represented types [PYJS1104]",
            "help: Use one represented type at this boundary, or use ordinary "
            "Python values throughout the union.",
        ),
        filename="callable_union.py",
    )


def test_direct_type_aliases_preserve_represented_storage():
    assert_semantics(
        """
        from pyjs import int8, js

        type Byte = int8

        @js
        def add(value: Byte) -> Byte:
            return value + 1

        def main() -> None:
            print(add(int8(127)))

        main()
        """
    )


def test_javascript_int64_uses_bigint_at_representation_boundaries():
    assert_module_analysis_transpile(
        """
        from pyjs import int64, js

        @js
        class Counter:
            value: int64

            def __init__(self, value: int64) -> None:
                self.value = value

            def add(self, amount: int64) -> int64:
                self.value = self.value + amount
                return self.value

        @js
        def choose(enabled: bool, value: int64) -> int64:
            offset = value if enabled else int64(1)
            return offset * 2

        def main() -> int64:
            counter = Counter(9_007_199_254_740_993)
            return choose(True, counter.add(2))
        """,
        """
        class Counter:

            def __init__(value: int) -> None:
                self.value = value

            def add(amount: int) -> int:
                self.value = normalize_int64(self.value.[int]__add__!(amount))
                return self.value

        def choose(enabled: bool, value: int) -> int:
            offset: int = value if enabled else int(1)
            return normalize_int64(offset.[int]__mul__!(int64_operand(2)))

        def main() -> int:
            counter: Counter = Counter(normalize_int64('9007199254740993'))
            return choose(True, counter.[Counter]add(normalize_int64(2)))
        """,
        """
        export class Counter {

            constructor(value) {
                this.value = value;
            }

            add(amount) {
                this.value = BigInt.asIntN(64, BigInt(this.value + amount));
                return this.value;
            }
        }

        export function choose(enabled, value) {
            var offset = enabled ? value : BigInt.asIntN(64,BigInt('1'));
            return BigInt.asIntN(64, BigInt(offset * BigInt(2)));
        }

        export function main() {
            var counter = new Counter(BigInt.asIntN(64, BigInt('9007199254740993')));
            return choose(true, counter.add(BigInt.asIntN(64, BigInt(2))));
        }
        """,
    )


def test_javascript_int64_matches_python_integer_semantics():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def adjust(value: int64) -> int64:
            return (value + 5) * 3

        def main() -> None:
            value: int64 = 9_007_199_254_740_993
            print(adjust(value))
            print(value // -2, value % -2)
            print(abs(-value), round(value), ~value)
            print(
                value == 9_007_199_254_740_993,
                value > 9_007_199_254_740_992,
            )

        main()
        """
    )


def test_sorted_orders_int64_without_losing_bigint_precision():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def main() -> None:
            values = [
                int64(9_007_199_254_740_993),
                int64(-9_007_199_254_740_993),
                int64(2),
            ]
            ordered = sorted(values)
            print(ordered[0], ordered[1], ordered[2])
            values.sort(reverse=True)
            print(values[0], values[1], values[2])

        main()
        """
    )


def test_int64_operations_do_not_wrap_plain_integer_operands():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def main() -> None:
            print(int64(0) == 2**64, int64(-(2**63)) < 2**64)
            print(int64(1) // 2**64, int64(1) % 2**64)
            print((2**64) // int64(3), (2**64) % int64(3))
            print(int64(-1) // (-(2**63) - 1))
            print(int64(-1) % (-(2**63) - 1))

        main()
        """
    )


def test_chained_int64_comparisons_preserve_large_plain_operands():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def main() -> None:
            print(0 < int64(1) < 9_007_199_254_740_993)
            print(9_007_199_254_740_993 > int64(1) > 0)

        main()
        """
    )


def test_int64_true_division_rounds_once_like_cpython():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def main() -> None:
            left = int64(-1465195632138975614)
            right = int64(6084712057446794809)
            print(left / right)
            print(int64(1) / int64(3))
            print(int64(-(2**63)) / int64(1))
            print(int64(3).__truediv__(int64(2)))
            print(int64(3).__rtruediv__(int64(2)))

        main()
        """
    )


def test_bool_left_operands_keep_python_integer_dispatch():
    assert_semantics(
        """
        from pyjs import int8, int64, js

        @js
        def main() -> None:
            value = int8(127)
            print(True + value)
            print((True - value) + 127)
            print((True * value) + 127)
            print((True // value) + 128)
            print((True % value) + 127)
            print((True ** value) + 127)
            print((True & value) + 127)
            print((True | value) + 127)
            print((True ^ value) + 127)
            print((True << int8(2)) + 127)
            print((True >> int8(2)) + 128)
            quotient, remainder = divmod(True, value)
            print(quotient + 128, remainder + 127)
            print(True + int64(127))
            print(True / int64(2))

        main()
        """
    )


def test_explicit_fixed_width_binary_methods_preserve_results():
    assert_semantics(
        """
        from pyjs import float32, int8, int64, js

        @js
        def main() -> None:
            print(int8(127).__add__(1))
            print(int8(-128).__sub__(1))
            print(int8(100).__mul__(2))
            print(int8(-7).__floordiv__(2))
            print(int8(-7).__mod__(2))
            print(int8(20).__pow__(3))
            print(int8(10).__or__(5))
            print(int8(10).__and__(12))
            print(int8(10).__xor__(15))
            print(int8(64).__lshift__(2))
            print(int8(-1).__rshift__(8))
            print(int64(9_223_372_036_854_775_807).__add__(1))
            print(int64(-7).__floordiv__(2))
            print(int64(-7).__mod__(2))
            print(int64(1).__lshift__(63))
            print((1).__add__(int64(2)))
            print((3).__floordiv__(int64(2)))
            print((3).__mod__(int64(2)))
            print((1).__or__(int64(2)))
            print((1).__lshift__(int64(2)))
            print(float32(16_777_216.0).__add__(1.0))
            print(float32(4097.0).__mul__(float32(4097.0)))
            print(float32(1.0).__truediv__(float32(10.0)))

        main()
        """
    )


def test_javascript_converts_int64_to_narrower_numbers_explicitly():
    assert_semantics(
        """
        from pyjs import float32, int8, int32, int64, js, uint32

        @js
        def main() -> None:
            value = int64(9_007_199_254_740_993)
            print(int8(value), int32(value), uint32(value))
            print(float32(int64(5)))
            print(int(int64(7)))

        main()
        """
    )


def test_javascript_rejects_unsafe_int64_to_python_int_conversion():
    actual, _javascript = run_javascript(
        """
        from pyjs import int64, js

        @js
        def main() -> None:
            try:
                int(int64(9_007_199_254_740_993))
            except ValueError:
                print("unsafe")

        main()
        """
    )

    assert actual == RuntimeResult(0, "unsafe\n", "")


def test_int64_works_in_python_integer_index_contexts():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def main() -> None:
            values = [10, 20, 30]
            values[int64(1)] = 21
            del values[int64(0)]
            values.insert(int64(1), 25)
            print(values[int64(0)], values.pop(int64(1)))
            values[int64(0):int64(1)] = [22]
            del values[int64(1):int64(2)]
            print(values[0], len(values))
            print(sum(range(int64(1), 5, int64(2))))
            print(list(enumerate([5], int64(2)))[0][0])
            print(sum([0, 1, 2, 3][int64(1):int64(3)]))
            print(sum([0, 1, 2, 3][::int64(2)]))
            print(len(int64(2) * [1]), len((1,) * int64(2)))
            print(int64(2) * "x", "y" * int64(2))
            print("abc"[int64(1)], (10, 20)[int64(1)])
            print(chr(int64(65)), int("10", int64(10)))
            print("a".zfill(int64(3)), "a".center(int64(3), "-"))
            print("abc".startswith("b", int64(1), int64(2)))
            print("aaaa".replace("a", "b", int64(2)))
            print("a b c".split(" ", int64(1))[1])
            print("ababa".rfind("a", int64(0), int64(4)))
            print([1, 2].index(2, int64(0)))

        main()
        """
    )


def test_javascript_rejects_int64_indices_that_cannot_be_exact_numbers():
    actual, javascript = run_javascript(
        """
        from pyjs import int64, js

        @js
        def main() -> None:
            try:
                range(int64(9_007_199_254_740_993))
            except ValueError:
                print("unsafe index")

        main()
        """
    )

    assert actual == RuntimeResult(0, "unsafe index\n", "")
    assert "Number.isSafeInteger" in javascript


def test_int64_decimal_f_string_formatting_remains_exact():
    assert_semantics(
        """
        from pyjs import int64, js

        @js
        def main() -> None:
            positive = int64(9_007_199_254_740_993)
            negative = int64(-9_007_199_254_740_993)
            print(f"{positive:d}")
            print(f"{positive:020d}")
            print(f"{negative:020d}")

        main()
        """
    )


def test_javascript_rejects_unsafe_int64_integer_math_results():
    actual, _javascript = run_javascript(
        """
        from math import ceil, floor
        from pyjs import int64, js

        @js
        def main() -> None:
            try:
                ceil(int64(9_007_199_254_740_993))
            except ValueError:
                print("unsafe result")
            try:
                floor(int64(9_007_199_254_740_993))
            except ValueError:
                print("unsafe result")

        main()
        """
    )

    assert actual == RuntimeResult(0, "unsafe result\nunsafe result\n", "")


def test_mixed_fixed_integer_and_float_arithmetic_stays_in_float_domain():
    assert_semantics(
        """
        from pyjs import int8, int64, js

        @js
        def main() -> None:
            value = int8(2)
            print(value + 2.5, 2.5 + value)
            print(value - 2.5, 2.5 - value)
            print(value * 2.5)
            print(2.5 * value)
            print(value / 2.5, 2.5 / value)

            wide = int64(9_007_199_254_740_993)
            print(wide + 0.5, 0.5 + wide)
            print(wide - 0.5, 0.5 - wide)
            print(wide * 0.5, 0.5 * wide)
            print(wide / 2.0, 2.0 / wide)

        main()
        """
    )


def test_javascript_int64_wraps_at_annotated_boundaries():
    actual, _javascript = run_javascript(
        """
        from pyjs import int64, js

        @js
        def increment(value: int64) -> int64:
            return value + 1

        @js
        def decrement(value: int64) -> int64:
            return value - 1

        @js
        def identity(value: int64) -> int64:
            return value

        def main() -> None:
            print(increment(9_223_372_036_854_775_807))
            print(decrement(increment(9_223_372_036_854_775_807)))
            print(identity(-9_223_372_036_854_775_808))

        main()
        """
    )

    assert actual == RuntimeResult(
        0,
        "-9223372036854775808\n9223372036854775807\n-9223372036854775808\n",
        "",
    )


def test_small_fixed_integer_constructors_accept_large_exact_literals():
    assert_semantics(
        """
        from pyjs import int8, int16, int32, js, uint8, uint16, uint32

        @js
        def main() -> None:
            print(int8(9_007_199_254_740_993), uint8(9_007_199_254_740_993))
            print(int16(9_007_199_254_740_993), uint16(9_007_199_254_740_993))
            print(int32(9_007_199_254_740_993), uint32(9_007_199_254_740_993))

        main()
        """
    )


def test_fixed_integer_constructors_fold_large_finite_float_literals():
    assert_semantics(
        """
        from pyjs import int8, int64, js, uint32

        @js
        def main() -> None:
            print(int8(1e20), uint32(-1e20))
            print(int64(1e19), int64(-1e19))

        main()
        """
    )


def test_fixed_integer_arithmetic_matches_javascript():
    assert_semantics(
        """
        from pyjs import int8, int16, int32, int64, js
        from pyjs import uint8, uint16, uint32

        @js
        def wrap_int8(value: int8) -> int8:
            return (value + 30) * 3

        def main() -> None:
            print(wrap_int8(int8(100)))
            print(uint8(-1))
            print(int16(32767) + 1)
            print(uint16(-1))
            print(int32(2147483647) + 1)
            print(uint32(-1))
            print(int64(9223372036854775807) + 1)
            print(int8(130.9))
            print(int8(64) << 2)
            print(uint8(255) >> 8)
            print(int8(-1) >> 8)
            print(int8(20) ** 3)
            print(abs(int8(-128)))
            print(~uint8(0))
            print(int32(2147483647) * 2147483647)
            print(uint32(4294967295) * 4294967295)
            print(int64(-130.9))

        main()
        """
    )


def assert_javascript_contract_result(contract, actual):
    assert actual.returncode == 0, actual.stderr
    result = int(actual.stdout)
    assert actual == RuntimeResult(0, "0\n", ""), contract.failure(result)


@pytest.mark.parametrize(
    "contract",
    [*BACKEND_CONTRACTS.values(), RANGE_LOOP_CONTRACT, BOOLEAN_NUMERIC_CONTRACT],
    ids=[*BACKEND_CONTRACTS, "range loop", "Boolean numerics"],
)
def test_shared_numeric_contract_runs_under_javascript(contract):
    actual, _javascript = run_javascript(contract.print_source)

    assert_javascript_contract_result(contract, actual)


def test_range_lookup_keeps_the_javascript_iterable_boundary():
    with pytest.raises(CompilationError, match="Attribute 'count' is not defined on 'Iterable__int'"):
        run_javascript(RANGE_NUMERIC_LOOKUP_CONTRACT.print_source)


@pytest.mark.parametrize("contract", [BINARY_POWER_CONTRACT, MODULAR_POWER_CONTRACT],
                         ids=["binary", "modular"])
def test_power_keeps_the_javascript_builtin_boundary(contract):
    with pytest.raises(CompilationError, match="Name 'power' is a Python value, not a client value"):
        run_javascript(contract.print_source)


def test_javascript_contract_process_failures_are_not_check_failures():
    contract = next(iter(BACKEND_CONTRACTS.values()))

    with pytest.raises(AssertionError, match="runtime failed") as caught:
        assert_javascript_contract_result(
            contract,
            RuntimeResult(1, "", "runtime failed"),
        )

    assert "contract check" not in str(caught.value)


@pytest.mark.parametrize(
    "source",
    PORTABLE_FAILURE_SOURCES.values(),
    ids=PORTABLE_FAILURE_SOURCES,
)
def test_portable_failure_contract_runs_under_javascript(source):
    actual, _javascript = run_javascript(source)

    assert actual.returncode == 1
    assert actual.stdout == ""


def test_fixed_integer_operations_diagnose_mixed_widths():
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        def combine(left: int8, right: int16) -> int:
            return left + right
        """,
        """
          File "mixed.py", line 5
            return left + right
                   ^^^^^^^^^^^^
        pyjs.CompilationError: different fixed-width numeric types cannot be mixed implicitly [PYJS1104]
        help: Convert the values to one fixed-width type first.
        """,
        filename="mixed.py",
    )


def test_target_numeric_types_do_not_leak_into_other_backends():
    assert_diagnostic(
        """
        from pyjs import js
        from pyjs.java import i32

        @js
        def identity(value: i32) -> i32:
            return value
        """,
        """
          File "java_numeric.py", line 5
            def identity(value: i32) -> i32:
                                        ^^^
        pyjs.CompilationError: java numeric types cannot compile for js [PYJS1104]
        help: Use a portable PyJS numeric type or a js-specific type explicitly.
        """,
        filename="java_numeric.py",
    )


def test_static_array_items_must_use_the_array_numeric_domain():
    assert_diagnostic(
        """
        from pyjs import StaticArray, js
        from pyjs.shader import i32

        @js
        def first(values: StaticArray[i32, 2]) -> i32:
            return values[0]
        """,
        """
          File "array_domain.py", line 5
            def first(values: StaticArray[i32, 2]) -> i32:
                                          ^^^
        pyjs.CompilationError: portable arrays cannot store wgsl values implicitly [PYJS1104]
        help: Use item and array types from the same numeric domain.
        """,
        filename="array_domain.py",
    )


def test_static_array_resizing_has_a_focused_diagnostic():
    assert_diagnostic(
        """
        from pyjs import StaticArray, js

        @js
        def resize(values: StaticArray[int, 2]) -> None:
            values.append(3)
        """,
        """
          File "static_array.py", line 5
            values.append(3)
            ^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Static arrays do not support append() [PYJS1104]
        help: Assign an existing item or create another static array.
        """,
        filename="static_array.py",
    )


@pytest.mark.parametrize(
    ("operation", "message", "caret"),
    (
        ("del values[0]", "item deletion", "    ^^^^^^^^^"),
        ("values[0:1] = [3]", "slice assignment", "^^^^^^^^^^^"),
    ),
)
def test_static_array_length_changing_syntax_has_a_focused_diagnostic(
    operation,
    message,
    caret,
):
    assert_diagnostic(
        f"""
        from pyjs import StaticArray, js

        @js
        def resize(values: StaticArray[int, 2]) -> None:
            {operation}
        """,
        f"""
          File "static_array.py", line 5
            {operation}
            {caret}
        pyjs.CompilationError: Static arrays do not support {message} [PYJS1104]
        help: Assign individual items without changing the array length.
        """,
        filename="static_array.py",
    )


@pytest.mark.parametrize("environment", [None, JVM_ENVIRONMENT, NATIVE_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "jvm", "llvm", "wasm"])
@pytest.mark.parametrize("operation", ["values[0:2] = [9]", "values[slice(0, 2)] = [9]",
                                       "values.__setitem__(slice(0, 2), [9])"])
def test_static_array_slice_spellings_cannot_resize_in_general_backends(environment, operation):
    # JS does not model first-class slice objects; the other general backends
    # must reject mutation just as they already reject literal slice stores.
    message = ("Name 'slice' is not defined" if environment is None and "slice(" in operation
               else "Static arrays do not support slice assignment")
    with pytest.raises(CompilationError, match=message) as caught:
        with analyze_source(f'''from pyjs import StaticArray, int8
def main() -> int:
    values = StaticArray[int8, 3]([1, 2, 3])
    {operation}
    return len(values)
''', filename="static_slices.py", environment=environment):
            pass
    assert caught.value.lineno == 4


def test_fixed_integer_assignments_diagnose_implicit_conversion():
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        def widen(value: int8) -> int16:
            return value
        """,
        """
          File "assignment.py", line 5
            return value
                   ^^^^^
        pyjs.CompilationError: different fixed-width numeric types cannot be assigned implicitly [PYJS1104]
        help: Convert the value to the destination fixed-width type first.
        """,
        filename="assignment.py",
    )


def test_method_overrides_preserve_numeric_parameter_formats():
    source = """
    from pyjs import int8, int16, js

    @js
    class Base:
        def choose(self, value: int8) -> int8:
            return value

    @js
    class Child(Base):
        def choose(self, value: int16) -> int8:
            return int8(value)

    @js
    def call(value: Base) -> int8:
        return value.choose(int8(1))

    def main() -> int8:
        return call(Child())
    """
    assert_diagnostic(
        source,
        diagnostic_text(
            "numeric_override.py",
            11,
            "def choose(self, value: int16) -> int8:",
            "^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Override Child.choose changes the "
            "represented storage contract [PYJS1103]",
            "help: Use the same fixed-width and StaticArray annotations as the "
            "base method.",
        ),
        filename="numeric_override.py",
    )


@pytest.mark.parametrize(
    "environment",
    (JVM_ENVIRONMENT, NATIVE_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT),
)
def test_general_backend_analysis_rejects_changed_override_storage(environment):
    source = """
    from pyjs import int8, int16, js

    @js
    class Base:
        def choose(self, value: int8) -> int8:
            return value

    @js
    class Child(Base):
        def choose(self, value: int16) -> int8:
            return int8(value)

    def main() -> int8:
        return Child().choose(int16(1))
    """

    with pytest.raises(
        CompilationError,
        match="Override Child.choose changes the represented storage contract",
    ):
        with analyze_source(source, environment=environment):
            pass


@pytest.mark.parametrize(
    ("base_return", "base_value", "child_return", "child_value"),
    (
        ("int8", "int8(0)", "int16", "int16(1)"),
        (
            "StaticArray[int, 2]",
            "StaticArray[int, 2]([0, 0])",
            "StaticArray[int, 3]",
            "StaticArray[int, 3]([1, 2, 3])",
        ),
    ),
)
def test_method_overrides_preserve_return_storage_formats(
    base_return,
    base_value,
    child_return,
    child_value,
):
    source = f"""
    from pyjs import StaticArray, int8, int16, js

    @js
    class Base:
        def choose(self) -> {base_return}:
            return {base_value}

    @js
    class Child(Base):
        def choose(self) -> {child_return}:
            return {child_value}

    @js
    def call(value: Base) -> {base_return}:
        return value.choose()

    def main() -> {base_return}:
        return call(Child())
    """
    child_line = f"def choose(self) -> {child_return}:"
    assert_diagnostic(
        source,
        diagnostic_text(
            "return_override.py",
            11,
            child_line,
            "^" * len(child_line),
            "pyjs.CompilationError: Override Child.choose changes the "
            "represented storage contract [PYJS1103]",
            "help: Use the same fixed-width and StaticArray annotations as the "
            "base method.",
        ),
        filename="return_override.py",
    )


def test_method_overrides_preserve_static_array_parameter_layouts():
    source = """
    from pyjs import StaticArray, js

    @js
    class Base:
        def choose(self, value: StaticArray[int, 2]) -> int:
            return value[0]

    @js
    class Child(Base):
        def choose(self, value: StaticArray[int, 3]) -> int:
            return value[0]

    @js
    def call(value: Base) -> int:
        return value.choose(StaticArray[int, 2]([1, 2]))

    def main() -> int:
        return call(Child())
    """
    child_line = "def choose(self, value: StaticArray[int, 3]) -> int:"
    assert_diagnostic(
        source,
        diagnostic_text(
            "array_override.py",
            11,
            child_line,
            "^" * len(child_line),
            "pyjs.CompilationError: Override Child.choose changes the "
            "represented storage contract [PYJS1103]",
            "help: Use the same fixed-width and StaticArray annotations as the "
            "base method.",
        ),
        filename="array_override.py",
    )


def test_method_overrides_preserve_compound_item_formats():
    source = """
    from pyjs import int8, int16, js

    @js
    class Base:
        def choose(self, value: list[int8]) -> int:
            return value[0]

    @js
    class Child(Base):
        def choose(self, value: list[int16]) -> int:
            return value[0]

    @js
    def call(value: Base) -> int:
        return value.choose([int8(1)])

    def main() -> int:
        return call(Child())
    """
    line = "def choose(self, value: list[int16]) -> int:"
    assert_diagnostic(
        source,
        diagnostic_text(
            "compound_override.py",
            11,
            line,
            "^" * len(line),
            "pyjs.CompilationError: Override Child.choose changes the "
            "represented storage contract [PYJS1103]",
            "help: Use the same fixed-width and StaticArray annotations as the "
            "base method.",
        ),
        filename="compound_override.py",
    )


def test_field_overrides_preserve_numeric_storage_formats():
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        class Base:
            value: int8

        @js
        class Child(Base):
            value: int16

        def main() -> Child:
            return Child()
        """,
        """
          File "field_override.py", line 10
            value: int16
                   ^^^^^
        pyjs.CompilationError: Cannot override inherited field 'Child.value' of type int8 with int16 [PYJS1103]
        note: field_override.py:6:12: Base.value is declared as int8 here
        help: Use a type compatible with int8 or change the declaration of Base.value.
        """,
        filename="field_override.py",
    )


def test_field_overrides_preserve_compound_item_formats():
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        class Base:
            values: list[int8]

        @js
        class Child(Base):
            values: list[int16]

        def main() -> Child:
            return Child()
        """,
        """
          File "compound_field.py", line 10
            values: list[int16]
                    ^^^^^^^^^^^
        pyjs.CompilationError: Cannot override inherited field 'Child.values' of type list[int8] with list[int16] [PYJS1103]
        note: compound_field.py:6:13: Base.values is declared as list[int8] here
        help: Use a type compatible with list[int8] or change the declaration of Base.values.
        """,
        filename="compound_field.py",
    )


def test_property_overrides_preserve_numeric_return_formats():
    source = """
    from pyjs import int8, int16, js

    @js
    class Base:
        @property
        def value(self) -> int8:
            return int8(1)

    @js
    class Child(Base):
        @property
        def value(self) -> int16:
            return int16(1)

    @js
    def read(value: Base) -> int8:
        return value.value

    def main() -> int8:
        return read(Child())
    """
    line = "def value(self) -> int16:"
    assert_diagnostic(
        source,
        diagnostic_text(
            "property_override.py",
            13,
            line,
            "^" * len(line),
            "pyjs.CompilationError: Override Child.value changes the "
            "represented storage contract [PYJS1103]",
            "help: Use the same fixed-width and StaticArray annotations as the "
            "base method.",
        ),
        filename="property_override.py",
    )


def test_property_setter_overrides_preserve_numeric_parameter_formats():
    source = """
    from pyjs import int8, int16, js

    @js
    class Base:
        @property
        def value(self) -> int:
            return 0

        @value.setter
        def value(self, new_value: int8) -> None:
            pass

    @js
    class Child(Base):
        @property
        def value(self) -> int:
            return 0

        @value.setter
        def value(self, new_value: int16) -> None:
            pass

    @js
    def write(value: Base) -> None:
        value.value = int8(1)

    def main() -> None:
        write(Child())
    """
    line = "def value(self, new_value: int16) -> None:"
    assert_diagnostic(
        source,
        diagnostic_text(
            "setter_override.py",
            21,
            line,
            "^" * len(line),
            "pyjs.CompilationError: Override Child.value changes the "
            "represented storage contract [PYJS1103]",
            "help: Use the same fixed-width and StaticArray annotations as the "
            "base method.",
        ),
        filename="setter_override.py",
    )


def test_fixed_integer_construction_diagnoses_non_numeric_values():
    assert_diagnostic(
        """
        from pyjs import int8, js

        @js
        def parse(value: str) -> int8:
            return int8(value)
        """,
        """
          File "constructor.py", line 5
            return int8(value)
                        ^^^^^
        pyjs.CompilationError: fixed-width numeric construction requires a number [PYJS1104]
        help: Pass an int or float value.
        """,
        filename="constructor.py",
    )


def test_mixed_fixed_and_plain_conditional_results_require_conversion():
    assert_diagnostic(
        """
        from pyjs import int8, js

        @js
        def choose(enabled: bool, value: int8) -> int:
            return value if enabled else 1
        """,
        """
          File "conditional.py", line 5
            return value if enabled else 1
                   ^^^^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Conditional branches use incompatible numeric representations [PYJS1103]
        help: Convert both branches to one fixed-width type, or use ordinary Python numbers in both branches.
        """,
        filename="conditional.py",
    )


def test_mixed_fixed_and_plain_branch_assignments_require_conversion():
    assert_diagnostic(
        """
        from pyjs import int8, js

        @js
        def choose(enabled: bool) -> int:
            if enabled:
                value = int8(1)
            else:
                value = 1
            return value
        """,
        """
          File "branches.py", line 5
            if enabled:
            ^^^^^^^^^^^
        pyjs.CompilationError: Branches assign incompatible numeric representations to 'value' [PYJS1103]
        help: Use an explicit fixed-width annotation to convert every branch, or keep every branch as an ordinary Python number.
        """,
        filename="branches.py",
    )


def test_mixed_static_and_plain_conditional_results_require_conversion():
    assert_diagnostic(
        """
        from pyjs import StaticArray, js

        @js
        def choose(enabled: bool, values: StaticArray[int, 2]) -> int:
            selected = values if enabled else [1, 2]
            return selected[0]
        """,
        """
          File "conditional_array.py", line 5
            selected = values if enabled else [1, 2]
                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Conditional branches use incompatible array layouts [PYJS1103]
        help: Use one StaticArray type in both branches, or use ordinary lists in both branches.
        """,
        filename="conditional_array.py",
    )


@pytest.mark.parametrize(
    "environment",
    (JVM_ENVIRONMENT, NATIVE_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT),
)
def test_native_analysis_rejects_mixed_conditional_representations(environment):
    source = """
    from pyjs import int8, js

    @js
    def choose(enabled: bool, value: int8) -> int:
        return value if enabled else 1

    def main() -> int:
        return choose(True, int8(1))
    """

    with pytest.raises(CompilationError, match="incompatible numeric representations"):
        with analyze_source(source, environment=environment):
            pass


@pytest.mark.parametrize(
    ("numeric_type", "literal"),
    (("i32", "2147483648"), ("u32", "-1"), ("u32", "4294967296")),
)
def test_general_backends_reject_out_of_range_wgsl_operands(
    numeric_type,
    literal,
):
    assert_diagnostic(
        f"""
        from pyjs import js
        from pyjs.shader import {numeric_type}

        @js
        def add(value: {numeric_type}) -> {numeric_type}:
            return value + {literal}
        """,
        f"""
          File "wgsl_literal.py", line 6
            return value + {literal}
                           {"^" * len(literal)}
        pyjs.CompilationError: {int(literal)} cannot be represented as {numeric_type} in WGSL [PYJS1104]
        help: Use a representable literal or explicitly convert another concrete WGSL integer value.
        """,
        filename="wgsl_literal.py",
    )


@pytest.mark.parametrize("numeric_type", ("i32", "u32"))
@pytest.mark.parametrize("operation", ("value + amount", "u32(amount)"))
def test_general_backends_reject_dynamic_python_integers_in_wgsl_operations(
    numeric_type,
    operation,
):
    expression = operation.replace("u32", numeric_type)
    marker_start = expression.index("amount")
    statement = f"return {expression}"
    assert_diagnostic(
        f"""
        from pyjs import js
        from pyjs.shader import {numeric_type}

        @js
        def convert(value: {numeric_type}, amount: int) -> {numeric_type}:
            {statement}
        """,
        diagnostic_text(
            "wgsl_dynamic.py",
            6,
            statement,
            " " * (len("return ") + marker_start) + "^^^^^^",
            "pyjs.CompilationError: Dynamic Python integers cannot enter WGSL "
            "integer operations [PYJS1104]",
            "help: Accept a pyjs.shader integer at this boundary, or use a "
            "statically representable literal.",
        ),
        filename="wgsl_dynamic.py",
    )


def test_contextual_hash_pattern_uses_contextual_wgsl_integer_arithmetic():
    from pyjs import wgsl
    from pyjs.shader import i32, u32

    @wgsl
    def integer_hash(cx: float, cy: float, salt: u32) -> float:
        h = (
            u32(i32(cx) + 1048576) * 73856093
            ^ u32(i32(cy) + 1048576) * 19349663
            ^ salt * 83492791
        )
        h = h ^ (h >> 16)
        h = h * 2135587861
        h = h ^ (h >> 15)
        h = h * 2246822507
        h = h ^ (h >> 16)
        return float(h >> 8) / 16777216.0

    assert integer_hash(0.0, 0.0, 1) == 0.5741242170333862


def test_wgsl_python_boundaries_coerce_arguments_before_strict_arithmetic():
    from pyjs import wgsl
    from pyjs.shader import i32, u32

    @wgsl
    def add(value: u32, amount: u32) -> u32:
        return value + amount

    assert add(1, 2) == u32(3)
    with pytest.raises(OverflowError):
        u32(1) + -1
    with pytest.raises(OverflowError):
        u32(1) + 4_294_967_296
    with pytest.raises(OverflowError):
        i32(1) + 2_147_483_648


def test_wgsl_python_boundaries_unwrap_aliases_and_annotated_scalars():
    assert_semantics(
        """
        from typing import Annotated

        from pyjs import wgsl
        from pyjs.shader import u32

        type Scalar = u32
        type WrappedScalar = Annotated[Scalar, "wrapped"]

        @wgsl
        def aliased(value: Scalar) -> Scalar:
            return value + 1

        @wgsl
        def wrapped(value: Annotated[u32, "scalar"]) -> Annotated[u32, "scalar"]:
            return value + 1

        @wgsl
        def aliased_wrapper(value: WrappedScalar) -> WrappedScalar:
            return value + 1

        @wgsl
        def defaulted(value: u32 = 4_294_967_295) -> u32:
            return value + 1

        def main() -> None:
            print(aliased(4_294_967_295))
            print(wrapped(4_294_967_295))
            print(aliased_wrapper(4_294_967_295))
            print(defaulted())

        main()
        """
    )


def test_wgsl_python_boundaries_resolve_aliases_declared_later():
    assert_semantics(
        """
        from typing import Annotated

        from pyjs import wgsl

        @wgsl
        def increment(value: Scalar) -> Scalar:
            return value + 1

        @wgsl
        def wrapped(
            value: Annotated[Scalar, "wrapped"],
        ) -> Annotated[Scalar, "wrapped"]:
            return value + 1

        from pyjs.shader import u32
        type Scalar = u32

        print(increment(4_294_967_295))
        print(wrapped(4_294_967_295))
        """
    )


def test_wgsl_python_boundaries_resolve_alias_targets_declared_later():
    assert_semantics(
        """
        from pyjs import wgsl

        type Scalar = Later

        @wgsl
        def increment(value: Scalar) -> Scalar:
            return value + 1

        from pyjs.shader import u32 as Later

        print(increment(4_294_967_295))
        """
    )


def test_wgsl_python_boundaries_resolve_explicit_string_annotations():
    assert_semantics(
        """
        from pyjs import wgsl
        from pyjs.shader import u32

        @wgsl
        def increment(value: "u32") -> "u32":
            return value + 1

        print(increment(4_294_967_295))
        """
    )


def test_wgsl_python_boundaries_retry_annotations_after_an_early_call():
    from pyjs import wgsl

    @wgsl
    def increment(value: Scalar) -> Scalar:
        return value + 1

    assert increment(4_294_967_295) == 4_294_967_296

    from pyjs.shader import u32

    type Scalar = u32

    assert increment(4_294_967_295) == u32(0)


def test_static_array_nested_literals_validate_every_length():
    assert_diagnostic(
        """
        from pyjs import StaticArray, js

        @js
        def main() -> int:
            values = StaticArray[StaticArray[int, 2], 2]([[1], [2]])
            return values[0][0]
        """,
        """
          File "nested_array.py", line 6
            values = StaticArray[StaticArray[int, 2], 2]([[1], [2]])
                                                          ^^^
        pyjs.CompilationError: Static array requires 2 items, got 1 [PYJS1104]
        help: Provide exactly the declared number of items.
        """,
        filename="nested_array.py",
    )


def test_static_array_items_reject_implicit_fixed_width_conversion():
    assert_diagnostic(
        """
        from pyjs import StaticArray, int8, int16, js

        @js
        def main() -> int8:
            values = StaticArray[int8, 1]([int16(257)])
            return values[0]
        """,
        """
          File "array_item.py", line 6
            values = StaticArray[int8, 1]([int16(257)])
                                           ^^^^^^^^^^
        pyjs.CompilationError: different fixed-width numeric types cannot be assigned implicitly [PYJS1104]
        help: Convert the value to the destination fixed-width type first.
        """,
        filename="array_item.py",
    )


def test_annotated_lists_preserve_fixed_width_items():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def first(values: list[int8]) -> int8:
            return values[0] + 1

        def main() -> None:
            print(first([int8(127)]))

        main()
        """
    )


def test_inferred_collections_preserve_fixed_width_items():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def first() -> int8:
            values = [int8(1)]
            return values[0] + 127

        def main() -> None:
            print(first())

        main()
        """
    )


def test_nested_collections_preserve_fixed_width_items():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def first(values: list[list[int8]]) -> int8:
            return values[0][0] + 1

        def main() -> None:
            print(first([[int8(127)]]))

        main()
        """
    )


def test_optional_boolean_fallback_preserves_fixed_width_items():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def consume(value: int8 | None) -> None:
            selected = value or int8(127)
            print(selected + 1)

        def main() -> None:
            consume(None)
            consume(int8(1))

        main()
        """
    )


def test_iterable_builtins_preserve_ordinary_collection_item_formats():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def consume(values: list[int8]) -> None:
            print(min(values) + 1)
            print(max(values) + 2)
            print(sum(values, int8(0)))

        def main() -> None:
            consume([int8(100), int8(127)])

        main()
        """
    )


def test_collection_operations_preserve_item_representations():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def main() -> None:
            values: list[int8] = [int8(127)]
            values.extend([int8(1)])
            values[1:] = [int8(2)]
            repeated = values * 2
            print(repeated[0] + 1)

            first = dict([("a", int8(127))])
            second = dict({"b": int8(127)})
            third = dict(c=int8(127))
            first.update(second)
            _key, popped = third.popitem()
            print(first["a"] + 1)
            print(popped + 1)

            selected: set[int8] = {int8(127)}
            selected.update({int8(1)})
            union = selected.union({int8(2)})
            combined = selected | {int8(3)}
            print(max(union) + 1)
            print(max(combined) + 1)

        main()
        """
    )


@pytest.mark.parametrize(
    ("statement", "marker"),
    (
        (
            "values.extend([int16(257)])",
            "               ^^^^^^^^^^",
        ),
        (
            "values[:] = [int16(257)]",
            "             ^^^^^^^^^^",
        ),
        (
            "mapping.update({'b': int16(257)})",
            "                     ^^^^^^^^^^",
        ),
        (
            "selected.update({int16(257)})",
            "                 ^^^^^^^^^^",
        ),
    ),
)
def test_collection_mutations_reject_incompatible_representations(
    statement,
    marker,
):
    assert_diagnostic(
        f"""\
        from pyjs import int8, int16, js

        @js
        def mutate(values: list[int8], mapping: dict[str, int8], selected: set[int8]) -> None:
            {statement}
        """,
        diagnostic_text(
            "collection_mutation.py",
            5,
            statement,
            marker,
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="collection_mutation.py",
    )


def test_typed_dict_fields_preserve_recursive_representations():
    assert_semantics(
        """
        from typing import NotRequired, TypedDict
        from pyjs import int8, js

        class Record(TypedDict):
            value: int8
            values: list[int8]
            optional: NotRequired[int8]

        @js
        def consume(record: Record) -> None:
            print(record["value"] + 1)
            print(record["values"][0] + 1)
            optional = record.get("optional")
            if optional is not None:
                print(optional + 1)

        def main() -> None:
            record: Record = {
                "value": int8(127),
                "values": [int8(127)],
                "optional": int8(127),
            }
            consume(record)

        main()
        """
    )


def test_typed_dict_writes_enforce_field_representations():
    assert_diagnostic(
        """\
        from typing import TypedDict
        from pyjs import int8, int16, js

        class Record(TypedDict):
            value: int8

        @js
        def update(record: Record) -> None:
            record["value"] = int16(2)
        """,
        diagnostic_text(
            "typed_dict_write.py",
            9,
            "record['value'] = int16(2)",
            "                  ^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="typed_dict_write.py",
    )


def test_typed_dict_constructors_enforce_field_representations():
    assert_diagnostic(
        """\
        from typing import TypedDict
        from pyjs import int8, int16, js

        class Record(TypedDict):
            value: int8

        @js
        def make() -> Record:
            return Record(value=int16(2))
        """,
        diagnostic_text(
            "typed_dict_constructor.py",
            9,
            "return Record(value=int16(2))",
            "                    ^^^^^^^^",
            "pyjs.CompilationError: different fixed-width numeric types "
            "cannot be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="typed_dict_constructor.py",
    )


def test_starred_unpacking_rejects_incompatible_item_representations():
    assert_diagnostic(
        """\
        from pyjs import int8, int16, js

        @js
        def unpack() -> None:
            values = (int8(1), int16(2), int8(3))
            first, *rest = values
        """,
        diagnostic_text(
            "starred_unpacking.py",
            6,
            "first, *rest = values",
            "^^^^^^^^^^^^",
            "pyjs.CompilationError: Starred unpacking items use incompatible "
            "nested representations [PYJS1104]",
            "help: Convert the values to one represented type before combining them.",
        ),
        filename="starred_unpacking.py",
    )


@pytest.mark.parametrize(
    ("expression", "description"),
    (
        ("values.get('missing', int16(2))", "Dictionary fallback values"),
        ("next(iter(values.values()), int16(2))", "Iterator fallback values"),
    ),
)
def test_fallbacks_reject_incompatible_value_representations(
    expression,
    description,
):
    assert_diagnostic(
        f"""\
        from pyjs import int8, int16, js

        @js
        def read(values: dict[str, int8]) -> None:
            print({expression})
        """,
        diagnostic_text(
            "represented_fallback.py",
            5,
            f"print({expression})",
            "      " + "^" * len(expression),
            f"pyjs.CompilationError: {description} use incompatible nested "
            "representations [PYJS1104]",
            "help: Convert the values to one represented type before combining them.",
        ),
        filename="represented_fallback.py",
    )


def test_generic_calls_preserve_recursive_representations():
    assert_semantics(
        """
        from collections.abc import Callable
        from pyjs import float32, int8, int16, js

        @js
        def identity[T](value: T) -> T:
            return value

        @js
        def apply[T](callback: Callable[[], T]) -> T:
            return callback()

        @js
        def transform[T, R](callback: Callable[[T], R], value: T) -> R:
            return callback(value)

        @js
        def transform_first[T, R](value: T, callback: Callable[[T], R]) -> R:
            return callback(value)

        @js
        def optional[T](callback: Callable[[T], T] | None, value: T) -> T:
            if callback is None:
                return value
            return callback(value)

        @js
        def first[T](**values: T) -> T:
            return values["selected"]

        @js
        def narrow() -> int8:
            return int8(127)

        @js
        def first_byte(values: list[int8]) -> int8:
            return values[0]

        def main() -> None:
            print(identity(int8(127)) + 1)
            print(identity([int8(127)])[0] + 1)
            print(apply(narrow) + 1)
            print(transform(lambda value: value + 1, int8(127)))
            print(transform(callback=lambda value: value + 1, value=int16(32767)))
            print(transform_first(int8(127), lambda value: value + 1))
            print(transform(lambda value: value + 1.0, float32(16777216.0)))
            print(transform(lambda values: values[0], [int8(127)]) + 1)
            print(optional(lambda value: value + 1, int8(127)))
            print(transform(first_byte, [int8(127)]) + 1)
            print(first(selected=int8(127)) + 1)

        main()
        """
    )


@pytest.mark.parametrize(
    ("annotation", "item", "expression"),
    (
        (
            "int8",
            "int8(127)",
            "first(Values()) + 1",
        ),
        (
            "list[int8]",
            "[int8(127)]",
            "first(Values())[0] + 1",
        ),
    ),
)
def test_generic_structural_iterables_preserve_recursive_representations(
    annotation,
    item,
    expression,
):
    assert_semantics(
        f"""
        from collections.abc import Iterable, Iterator
        from pyjs import int8, js

        @js
        class Values:
            def __iter__(self) -> Iterator[{annotation}]:
                return iter([{item}])

        @js
        def first[T](values: Iterable[T]) -> T:
            for value in values:
                return value
            raise ValueError("empty")

        @js
        def show() -> None:
            print({expression})

        def main() -> None:
            show()

        main()
        """
    )


def test_generic_union_iterables_preserve_item_representations():
    assert_semantics(
        """
        from collections.abc import Iterable
        from pyjs import int8, js

        @js
        def first[T](values: Iterable[T]) -> T:
            for value in values:
                return value
            raise ValueError("empty")

        @js
        def show(values: list[int8] | tuple[int8, ...]) -> None:
            print(first(values) + 1)

        def main() -> None:
            show([int8(127)])

        main()
        """
    )


def test_optional_structural_iterables_preserve_item_representations():
    assert_semantics(
        """
        from collections.abc import Iterable, Iterator
        from pyjs import int8, js

        @js
        class Values:
            def __iter__(self) -> Iterator[int8]:
                return iter([int8(127)])

        @js
        def show(values: Iterable[int8] | None) -> None:
            if values is None:
                return
            for value in values:
                print(value + 1)

        def main() -> None:
            show(Values())

        main()
        """
    )


def test_async_generic_calls_preserve_result_representations():
    assert_semantics(
        """
        import asyncio
        from pyjs import int8, js

        @js
        async def identity[T](value: T) -> T:
            return value

        @js
        async def main() -> None:
            print(await identity(int8(127)) + 1)

        asyncio.run(main())
        """
    )


@pytest.mark.parametrize(
    ("expression", "marker"),
    (
        ("Box(int8(127))", "int8(127)"),
        ("Box[int8](int8(127))", "int8"),
        (
            "Box(StaticArray[int8, 1]([127]))",
            "StaticArray[int8, 1]([127])",
        ),
    ),
)
def test_generic_classes_reject_represented_type_arguments(expression, marker):
    line = f"{expression}"
    assert_diagnostic(
        f"""\
        from pyjs import StaticArray, int8, js

        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value

        @js
        def main() -> None:
            {expression}

        main()
        """,
        diagnostic_text(
            "represented_generic_class.py",
            10,
            line,
            " " * line.index(marker) + "^" * len(marker),
            "pyjs.CompilationError: Generic classes cannot use represented "
            "type arguments [PYJS2001]",
            "help: Use a concrete class with fixed-width or StaticArray field "
            "annotations.",
        ),
        filename="represented_generic_class.py",
    )


def test_ordinary_parameters_reject_represented_arguments():
    assert_diagnostic(
        """\
        from pyjs import int8, js

        @js
        def consume(value: int) -> None:
            print(value + 1)

        @js
        def main() -> None:
            consume(int8(127))
        """,
        diagnostic_text(
            "ordinary_parameter.py",
            9,
            "consume(int8(127))",
            "        ^^^^^^^^^",
            "pyjs.CompilationError: Argument uses a represented value where "
            "an ordinary Python value is required [PYJS1104]",
            "help: Convert it to the annotated Python type, or change the "
            "parameter to the represented type.",
        ),
        filename="ordinary_parameter.py",
    )


def test_generic_parameters_reject_incompatible_representations():
    assert_diagnostic(
        """\
        from pyjs import int8, int16, js

        @js
        def choose[T](left: T, right: T) -> T:
            return left

        @js
        def main() -> None:
            print(choose(int8(1), int16(2)))
        """,
        diagnostic_text(
            "generic_parameter.py",
            9,
            "print(choose(int8(1), int16(2)))",
            "                      ^^^^^^^^",
            "pyjs.CompilationError: Type variable arguments use incompatible "
            "representations [PYJS1104]",
            "help: Pass one represented type for each generic type parameter.",
        ),
        filename="generic_parameter.py",
    )


def test_conditional_callables_reject_incompatible_result_representations():
    expression = "narrow if enabled else wide"
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        def narrow() -> int8:
            return int8(127)

        @js
        def wide() -> int16:
            return int16(127)

        @js
        def choose(enabled: bool) -> None:
            callback = narrow if enabled else wide
            print(callback() + 1)
        """,
        diagnostic_text(
            "callable_conditional.py",
            13,
            f"callback = {expression}",
            " " * len("callback = ") + "^" * len(expression),
            "pyjs.CompilationError: Conditional branches use incompatible "
            "nested representations [PYJS1103]",
            "help: Use one represented type for each runtime value type, or "
            "add an explicit conversion.",
        ),
        filename="callable_conditional.py",
    )


def test_branches_reject_incompatible_nested_representations():
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        def choose(enabled: bool) -> None:
            if enabled:
                values = [int8(127)]
            else:
                values = [int16(127)]
            print(values[0] + 1)
        """,
        diagnostic_text(
            "nested_branch.py",
            5,
            "if enabled:",
            "^" * len("if enabled:"),
            "pyjs.CompilationError: Branches assign incompatible nested "
            "representations to 'values' [PYJS1103]",
            "help: Use one represented type for each runtime value type, or "
            "add an explicit conversion.",
        ),
        filename="nested_branch.py",
    )


@pytest.mark.parametrize(
    ("expression", "description"),
    (
        ("[int8(127), int16(127)]", "List items"),
        ("{int8(127), int16(127)}", "Set items"),
        ("{'a': int8(127), 'b': int16(127)}", "Dictionary values"),
    ),
)
def test_collection_literals_reject_incompatible_item_representations(
    expression,
    description,
):
    assert_diagnostic(
        f"""
        from pyjs import int8, int16, js

        @js
        def choose() -> None:
            values = {expression}
            print(values[0] + 1)
        """,
        diagnostic_text(
            "mixed_list.py",
            5,
            f"values = {expression}",
            " " * len("values = ") + "^" * len(expression),
            f"pyjs.CompilationError: {description} use incompatible nested "
            "representations [PYJS1104]",
            "help: Convert the values to one represented type before combining them.",
        ),
        filename="mixed_list.py",
    )


def test_dynamic_tuple_index_rejects_indistinguishable_item_formats():
    expression = "values[index]"
    assert_diagnostic(
        """
        from pyjs import int8, int16, js

        @js
        def choose(index: int) -> None:
            values = (int8(127), int16(127))
            print(values[index] + 1)
        """,
        diagnostic_text(
            "dynamic_tuple.py",
            6,
            f"print({expression} + 1)",
            " " * len("print(") + "^" * len(expression),
            "pyjs.CompilationError: Dynamic tuple index has incompatible item "
            "representations [PYJS1104]",
            "help: Use a literal index or convert equal runtime types to one "
            "represented type first.",
        ),
        filename="dynamic_tuple.py",
    )


def test_collection_writes_preserve_fixed_width_items():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def mutate(values: list[int8], mapping: dict[str, int8]) -> None:
            values.append(int8(127))
            values[0] = int8(127)
            mapping["answer"] = int8(127)
            print(values[0] + 1, values[1] + 1, mapping["answer"] + 1)

        def main() -> None:
            mutate([int8(0)], {})

        main()
        """
    )


def test_mapping_methods_preserve_fixed_width_values():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def consume(values: dict[str, int8]) -> None:
            found = values.get("found")
            if found is not None:
                print(found + 1)
            print(values.get("missing", int8(127)) + 1)
            print(values.setdefault("created", int8(127)) + 1)
            print(values.pop("created") + 1)

        def main() -> None:
            consume({"found": int8(127)})

        main()
        """
    )


def test_collection_pop_preserves_fixed_width_items():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def consume(values: list[int8], unique: set[int8]) -> None:
            print(values.pop() + 1, unique.pop() + 1)

        def main() -> None:
            consume([int8(127)], {int8(127)})

        main()
        """
    )


@pytest.mark.parametrize(
    "statement",
    (
        "values.append(int16(1))",
        "values[0] = int16(1)",
    ),
)
def test_collection_writes_reject_incompatible_item_formats(statement):
    assert_diagnostic(
        f"""
        from pyjs import int8, int16, js

        @js
        def mutate(values: list[int8]) -> None:
            {statement}
        """,
        diagnostic_text(
            "collection_write.py",
            5,
            statement,
            " " * statement.index("int16") + "^" * len("int16(1)"),
            "pyjs.CompilationError: different fixed-width numeric types cannot "
            "be assigned implicitly [PYJS1104]",
            "help: Convert the value to the destination fixed-width type first.",
        ),
        filename="collection_write.py",
    )


def test_collection_arguments_require_matching_item_representations():
    statement = "consume(values)"
    assert_diagnostic(
        f"""
        from pyjs import int8, js

        @js
        def consume(values: list[int8]) -> None:
            pass

        @js
        def main(values: list[int]) -> None:
            {statement}
        """,
        diagnostic_text(
            "collection_argument.py",
            10,
            statement,
            " " * statement.index("values") + "^" * len("values"),
            "pyjs.CompilationError: Value uses an incompatible nested "
            "representation [PYJS1104]",
            "help: Convert each represented value explicitly.",
        ),
        filename="collection_argument.py",
    )


def test_static_array_parameters_preserve_literal_item_formats():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def first(values: StaticArray[int8, 1]) -> int8:
            return values[0]

        def main() -> None:
            print(first([int8(130)]))

        main()
        """
    )


def test_static_array_unpacking_preserves_scalar_and_nested_item_formats():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            value, = StaticArray[int8, 1]([1])
            row, = StaticArray[StaticArray[int8, 1], 1]([[1]])
            print(value + 127, row[0] + 127)

        main()
        """
    )


def test_nested_static_array_loop_unpacking_preserves_item_formats():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            rows = StaticArray[StaticArray[int8, 2], 1]([[1, 127]])
            for first, second in rows:
                print(first + 127, second + 1)

        main()
        """
    )


def test_static_array_starred_unpacking_preserves_represented_items():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def unpack(values: StaticArray[int8, 2]) -> None:
            first, *rest = values
            print(first + 127, rest[0] + 1)

        def main() -> None:
            unpack(StaticArray[int8, 2]([1, 127]))

        main()
        """
    )


def test_with_bindings_preserve_scalar_and_static_array_formats():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        class ScalarContext:
            def __enter__(self) -> int8:
                return int8(1)

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        @js
        class ArrayContext:
            def __enter__(self) -> StaticArray[int8, 1]:
                return StaticArray[int8, 1]([1])

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        @js
        def main() -> None:
            with ScalarContext() as value:
                print(value + 127)
            with ArrayContext() as values:
                print(values[0] + 127)

        main()
        """
    )


def test_boolean_expressions_preserve_scalar_and_static_array_formats():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            left = int8(1)
            right = int8(2)
            selected = left and right
            first = StaticArray[int8, 1]([1])
            second = StaticArray[int8, 1]([2])
            values = first and second
            print(selected + 126, values[0] + 126)

        main()
        """
    )


def test_value_preserving_builtins_keep_fixed_width_results():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def main() -> None:
            print(min(int8(127), int8(126)) + 2)
            print(max(int8(126), int8(127)) + 1)

        main()
        """
    )


def test_iterable_min_and_max_keep_static_array_item_formats():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            values = StaticArray[int8, 2]([126, 127])
            print(min(values) + 2)
            print(max(values) + 1)

        main()
        """
    )


def test_sum_reduces_static_array_items_in_their_fixed_width_type():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def main() -> None:
            values = StaticArray[int8, 2]([100, 100])
            print(sum(values))

        main()
        """
    )


def test_sum_rounds_each_static_float32_addition():
    assert_semantics(
        """
        from pyjs import StaticArray, float32, js

        @js
        def main() -> None:
            values = StaticArray[float32, 3]([16777216.0, 1.0, -16777216.0])
            print(sum(values))

        main()
        """
    )


def test_sum_uses_bigint_for_static_int64_items():
    assert_semantics(
        """
        from pyjs import StaticArray, int64, js

        @js
        def main() -> None:
            values = StaticArray[int64, 2]([9223372036854775807, 1])
            print(sum(values))

        main()
        """
    )


def test_divmod_preserves_represented_tuple_items():
    assert_semantics(
        """
        from pyjs import int8, int64, js

        @js
        def split(value: int8) -> None:
            quotient, remainder = divmod(value, 2)
            print(quotient + 65, remainder + 127)
            minimum_quotient, minimum_remainder = divmod(int8(-128), -1)
            print(minimum_quotient, minimum_remainder)
            wide_quotient, wide_remainder = divmod(
                int64(9223372036854775807),
                3,
            )
            reflected_quotient, reflected_remainder = divmod(
                1677624431168367,
                int64(3),
            )
            print(wide_quotient, wide_remainder)
            print(reflected_quotient, reflected_remainder)

        def main() -> None:
            split(int8(127))

        main()
        """
    )


def test_fixed_width_variadic_parameters_preserve_item_formats():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def first(*values: int8) -> int8:
            return values[0] + 1

        def main() -> None:
            print(first(int8(127)))

        main()
        """
    )


def test_fixed_width_variadic_keywords_preserve_item_formats():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def first(**values: int8) -> int8:
            return values["value"] + 1

        def main() -> None:
            print(first(value=int8(127)))

        main()
        """
    )


def test_static_array_cannot_widen_to_a_mutable_list_parameter():
    assert_diagnostic(
        """
        from pyjs import StaticArray, js

        @js
        def resize(values: list[int]) -> None:
            values.append(3)

        @js
        def main(values: StaticArray[int, 2]) -> None:
            resize(values)
        """,
        """
          File "array_widening.py", line 10
            resize(values)
                   ^^^^^^
        pyjs.CompilationError: StaticArray cannot be widened to a mutable list [PYJS1104]
        help: Keep the matching StaticArray type, or explicitly convert each item while building an ordinary list.
        """,
        filename="array_widening.py",
    )


@pytest.mark.parametrize(
    "statement",
    (
        "result = values[:][0] + 1",
        "result = list(values)[0] + 1",
        "result = tuple(values)[0] + 1",
        "result = [*values][0] + 1",
        "result = values.copy()[0] + 1",
        "result = next(iter(values)) + 1",
        "result = next(reversed(values)) + 1",
        "result = consume(*values)",
        "result = next(iter(enumerate(values)))[1] + 1",
        "result = next(iter(filter(None, values))) + 1",
        "result = next(iter(map(abs, values))) + 1",
        "result = sorted(values)[0] + 1",
        "result = next(iter(zip(values)))[0] + 1",
    ),
)
def test_static_array_extractions_preserve_represented_items(statement):
    assert_semantics(
        f"""
        from pyjs import StaticArray, int8, js

        @js
        def consume(*values: int8) -> int8:
            return values[0] + 1

        @js
        def extract(values: StaticArray[int8, 1]) -> None:
            {statement}
            print(result)

        def main() -> None:
            extract(StaticArray[int8, 1]([127]))

        main()
        """
    )


def test_static_array_concatenation_preserves_represented_items():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def concatenate(values: StaticArray[int8, 1]) -> None:
            print((values + values)[0] + 1)

        def main() -> None:
            concatenate(StaticArray[int8, 1]([127]))

        main()
        """
    )


@pytest.mark.parametrize(
    "statement",
    (
        "result = [value for value in values][0] + 1",
        "result = next(iter({value for value in values})) + 1",
        "result = next(iter({value: value for value in values}.values())) + 1",
        "result = next(value for value in values) + 1",
    ),
)
def test_comprehensions_preserve_represented_static_array_items(statement):
    assert_semantics(
        f"""
        from pyjs import StaticArray, int8, js

        @js
        def extract(values: StaticArray[int8, 1]) -> None:
            {statement}
            print(result)

        def main() -> None:
            extract(StaticArray[int8, 1]([127]))

        main()
        """
    )


def test_comprehensions_preserve_nested_static_array_items():
    assert_semantics(
        """
        from pyjs import StaticArray, int8, js

        @js
        def extract(
            values: StaticArray[StaticArray[int8, 1], 1],
        ) -> None:
            copied = [row for row in values]
            print(copied[0][0] + 1)

        def main() -> None:
            extract(StaticArray[StaticArray[int8, 1], 1]([[127]]))

        main()
        """
    )


@pytest.mark.parametrize(
    "expression",
    (
        "lambda: int8(127)",
        "lambda: StaticArray[int8, 1]([127])",
    ),
)
def test_lambdas_preserve_represented_results(expression):
    access = (
        "callback() + 1" if expression == "lambda: int8(127)" else "callback()[0] + 1"
    )
    assert_semantics(
        f"""
        from pyjs import StaticArray, int8, js

        @js
        def make() -> None:
            callback = {expression}
            print({access})

        make()
        """
    )


@pytest.mark.parametrize(
    "expression",
    ("int8(1)", "StaticArray[int, 1]([1])"),
)
def test_generators_preserve_represented_yields(expression):
    access = "next(iterator) + 1" if expression == "int8(1)" else "next(iterator)[0]"
    assert_semantics(
        f"""
        from pyjs import StaticArray, int8, js

        @js
        def values():
            yield {expression}

        def main() -> None:
            iterator = values()
            print({access})

        main()
        """
    )


def test_generators_preserve_optional_represented_yields():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def values():
            yield int8(127)
            yield None

        @js
        def main() -> None:
            for value in values():
                if value is not None:
                    print(value + 1)

        main()
        """
    )


def test_map_preserves_represented_callback_results():
    assert_semantics(
        """
        from pyjs import int8, js

        @js
        def narrow(value: int) -> int8:
            return int8(value)

        @js
        def main() -> None:
            values = map(narrow, [127])
            print(next(values) + 1)

        main()
        """
    )


def test_dynamic_float_to_fixed_integer_conversion_is_rejected():
    assert_diagnostic(
        """
        from pyjs import int8, js

        @js
        def convert(value: float) -> int8:
            return int8(value)
        """,
        """
          File "float_conversion.py", line 5
            return int8(value)
                        ^^^^^
        pyjs.CompilationError: fixed-width integer conversion requires a finite float literal [PYJS1104]
        help: Validate and convert a dynamic float to int before constructing a fixed-width integer.
        """,
        filename="float_conversion.py",
    )


@pytest.mark.parametrize(
    "expression",
    ('float("nan")', 'float("inf")', 'float("-inf")'),
)
def test_non_finite_fixed_integer_construction_is_rejected(expression):
    source = f"""
    from pyjs import int8, js

    @js
    def main() -> int8:
        return int8({expression})
    """

    with pytest.raises(CompilationError, match="requires a finite float literal"):
        with analyze_source(source):
            pass
