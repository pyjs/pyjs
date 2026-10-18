"""Native format mini-language, application protocols and checked lifetimes."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case
from tests.native.runtime_support import MEMORY_SANITIZERS


@pytest.mark.parametrize("value, specification", [(1234567, ".,"), (1234.5678, "7._"), ("text", "._s")])
@pytest.mark.parametrize("erased", [False, True])
def test_fractional_grouping_without_precision_is_a_located_boundary(value, specification, erased):
    # Valid Python 3.14 syntax is unsupported here, not a runtime ValueError.
    assert isinstance(format(value, specification), str)
    annotation = "object" if erased else type(value).__name__
    source = (f"def show(value: {annotation}) -> str:\n    return format(value, {specification!r})\n"
              f"def main() -> str:\n    return show({value!r})\n")
    with pytest.raises(LLVMUnsupported, match="LLVM format supports.*at line"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_precision_dot_still_requires_digits_or_fractional_grouping(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            try:
                return format(12.5, ".")
            except ValueError:
                return "invalid"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_formats(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            value = -42
            floating = 1.25
            return (f"{value:08d}|{value:10d}|{True:03d}|{floating:.2f}|"
                    + format(123, "+08d") + "|" + format(0.125, "10.2%")
                    + "|" + format(-2.5, "010.2E") + "|" + format(3.5, ".3g"))
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_precision_without_type_code_raises_value_error(optimize):
    LLVM().assert_matches_python('''
        def integer(value: int) -> str:
            try:
                return format(value, ".2")
            except ValueError as error:
                return str(error)

        def boolean(value: bool) -> str:
            try:
                return f"{value:08.3}"
            except ValueError as error:
                return str(error)

        def main() -> str:
            return integer(5) + "|" + integer(-5) + "|" + boolean(True) + "|" + boolean(False)
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("value, specification", [
    (1, "9" * 4500 + "d"),
    (1.25, "." + "9" * 4500 + "f"),
    (1, "0" * 4500 + "1d"),
    (1.25, "." + "0" * 4500 + "2f"),
    ("é😀", ".2147483647s"),
    ("é😀abc", ".4294967296"),
    ("é😀abc", ".4294967298s"),
    ("é😀", ".9223372036854775807"),
    ("é😀", ".9223372036854775808s"),
], ids=["width-overflow", "precision-overflow", "zero-prefixed-width", "zero-prefixed-precision",
        "string-precision-above-int32", "string-precision-low32-zero", "string-precision-low32-two",
        "string-precision-int64-max", "string-precision-overflow"])
def test_decimal_format_bounds_precede_host_integer_conversion(value, specification, optimize):
    source = f'''
        def main() -> str:
            try:
                return format({value!r}, {specification!r})
            except ValueError:
                return "caught"
    '''
    LLVM().assert_matches_python(source, optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("source, floating", [
    ('def main() -> str:\n    return f"constant"', False),
    ('def main() -> str:\n    return f"{42:08d}"', False),
    ('def main() -> str:\n    return f"{\"é\":😀^8s}"', False),
    ('def main() -> str:\n    return format(1.25, ".2f")', True),
    ('def main() -> str:\n    return format(42, ".2f")', True),
])
def test_scalar_formatting_does_not_require_dom_or_gc(source, floating):
    result = LLVM().assert_matches_python(source, optimize=2)
    # Large runtime IR is intentionally not goldenized. These boundaries keep
    # scalar formatters free of DOM/GC and unused floating-format dependencies.
    assert "@pyjs.gc.try.alloc" not in result.native.llvm_ir
    assert "@pyjs.native.output" not in result.native.llvm_ir
    assert ("@pyjs.format.float(" in result.native.llvm_ir) == floating


@pytest.mark.parametrize("optimize", [0, 2])
def test_format_order_conversion_default_arguments_and_shadowing(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            events: list[str]

            def __init__(self, events: list[str]) -> None:
                self.events = events

            def __repr__(self) -> str:
                self.events.append("repr")
                return "é😀"

            def __str__(self) -> str:
                self.events.append("str")
                return "display"

            def __format__(self, spec: str, *, suffix: str = "!") -> str:
                self.events.append("format:" + spec)
                gc_collect()
                return spec + suffix

        def item(events: list[str]) -> Item:
            events.append("value")
            return Item(events)

        def specification(events: list[str]) -> str:
            events.append("spec")
            return "computed"

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            # These local names must not intercept implicit f-string operations.
            format = 1
            str = 2
            repr = 3
            ascii = 4
            result = f"{item(events):{specification(events)}}|{item(events)!r}|{item(events)!s}|{item(events)!a}"
            return result + "|" + ",".join(events)
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("optimize", [0, 2])
def test_format_exceptions_recursion_and_recovery(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __format__(self, spec: str) -> str:
                if spec == "loop":
                    return format(self, "loop")
                if spec == "fail":
                    raise ValueError("formatting failed")
                return "ok"

        def main() -> str:
            gc_set_threshold(1)
            item = Item()
            result = ""
            for index in range(4):
                try:
                    result += f"{item:fail}"
                except ValueError as error:
                    result += str(error)
                try:
                    result += format(item, "loop")
                except RecursionError:
                    result += "recursive"
                gc_collect()
                result += f"{item}"
            try:
                result += format("x", "+5s")
            except ValueError:
                result += "invalid"
            try:
                result += format([1], "d")
            except TypeError:
                result += "unsupported"
            return result
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("optimize", [0, 2])
def test_format_library_numeric_edges(tmp_path, optimize):
    specs = [".0f", ".2f", "013.4f", "+14.6e", "020.4E", " .3g", "*>20.6G", "^18.2%", "08F"]
    source = "def render(value: float) -> str:\n    return " + " + '|' + ".join(f"format(value, {spec!r})" for spec in specs)
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    for value in [0.0, -0.0, 0.125, -1.25, 2.675, 1.005, 1e-307, 5e-324, 1e308, float("inf"), -float("inf"), float("nan"), float("-nan")]:
        assert library.render(value) == "|".join(format(value, spec) for spec in specs)


@pytest.mark.parametrize("optimize", [0, 2])
def test_format_portable_values_and_empty_optional(optimize):
    LLVM().assert_matches_python('''
        from pyjs import int8, uint32, int64, float32

        def optional(value: int | None) -> str:
            return format(value) + ascii(value)

        def main() -> str:
            return (format(int8(128), "08d") + format(uint32(-1), "20d")
                    + format(int64(-9223372036854775808), "025d")
                    + format(float32(1.1), ".9f")
                    + optional(1) + optional(None) + format(()) + ascii({}))
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_optional_and_exception_fstrings(optimize):
    LLVM().assert_matches_python('''
        class Item:
            def __format__(self, spec: str) -> str:
                return "custom"

        def render(value: Item | None) -> str:
            return f"{value}"

        def main() -> str:
            result = render(Item()) + render(None)
            try:
                raise ValueError("problem")
            except ValueError as error:
                result += f"{str(error)}"
            return result
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("method, diagnostic", [
    ('def __format__(self, spec: str) -> int:\n        return 1', "must return str"),
    ('def __format__(self, spec: int) -> str:\n        return "x"', "must accept a string"),
    ('@staticmethod\n    def __format__(spec: str) -> str:\n        return spec', "requires an instance method"),
])
def test_format_method_contract_diagnostics(method, diagnostic):
    source = "class Item:\n    " + method + '\ndef main() -> str:\n    return format(Item(), "spec")'
    with pytest.raises(LLVMUnsupported, match=diagnostic + ".*at line"):
        transpile_llvm(source)


def test_subclass_only_format_protocol_is_not_ignored():
    with pytest.raises(LLVMUnsupported, match="static base requires an explicit __format__.*at line"):
        transpile_llvm('''
            class Base:
                def __str__(self) -> str:
                    return "base"
            class Child(Base):
                def __format__(self, spec: str) -> str:
                    return "child"
            def render(value: Base) -> str:
                return format(value)
            def main() -> str:
                return render(Child())
        ''')


def test_custom_format_does_not_reach_unrelated_string_methods():
    LLVM().assert_matches_python('''
        class Item:
            def __format__(self, spec: str) -> str:
                return "custom:" + spec

            def __str__(self) -> str:
                return unavailable_host_feature()

        def main() -> str:
            return f"{Item():test}"
    ''', optimize=2)


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_base_format_pipeline(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            value = -9223372036854775808
            return (f"{value:#080b}|{value:#025o}|{value:+#025x}|{value:😀^25X}|"
                    + format(0, "#010b") + format(255, "0=+#15x") + format(42, "#d"))
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("body, diagnostic", [
    ('return format(1, ",d")', "LLVM format supports"),
    ('return format(1.25, "+10")', "signed/alternate float formats require"),
    ('spec = "5d"\n    return format(1, spec)', "constant format specification"),
    ('return format(str)', "class objects"),
])
def test_format_boundaries_have_located_diagnostics(body, diagnostic):
    with pytest.raises(LLVMUnsupported, match=diagnostic + ".*at line"):
        transpile_llvm("def main() -> str:\n    " + body)


@pytest.mark.parametrize("optimize", [0, 2])
def test_format_allocation_failure_recovery(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        def render(value: str) -> str:
            return f"{value:😀^200.80s}|{value!a}|{-12.5:030.8e}|{42:+010d}"

        def main() -> int:
            gc_set_threshold(1)
            value = "é中😀" * 20
            expected = render(value)
            failures = 0
            for attempt in range(1, 160):
                arm(attempt)
                complete = False
                try:
                    result = render(value)
                    arm(0)
                    complete = True
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert render(value) == expected
                if complete:
                    assert result == expected and failures > 0
                    return 0
            return 2
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_unicode_alignment_ascii_and_precision(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            value = "é中😀"
            return (f"{value:😀^9.2s}|{value!r:>15}|{value!a:<30}|"
                    + format(value, ".0s") + format(value, "09")
                    + ascii([value, "x\\n"]) + format([1, 2]) + format(True))
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_format_dispatch_and_dynamic_specs(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __format__(self, spec: str) -> str:
                return "base:" + spec

        class Child(Base):
            def __format__(self, spec: str) -> str:
                gc_collect()
                return "child:" + spec

        def render(value: Base, spec: str) -> str:
            return format(value, spec) + f"|{value:{spec}}|{value}"

        def main() -> str:
            gc_set_threshold(1)
            return render(Child(), "application-defined")
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)
