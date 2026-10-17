"""Native JSON text is compared byte-for-byte, not by parsing it again."""

import json
import subprocess
import sys
from textwrap import dedent

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


def check(source, optimize):
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("ensure_ascii", [True, False])
def test_borrowed_json_strings_cross_escape_and_buffer_boundaries(tmp_path, optimize, ensure_ascii):
    library = LLVM().compile_library(f'''
        import json
        def render(value: str) -> str:
            return json.dumps({{value: [value, "", value]}}, ensure_ascii={ensure_ascii})
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        boundaries = ''.join(chr(value) for value in (
            0x7F, 0x80, 0x7FF, 0x800, 0x2028, 0x2029,
            0xD7FF, 0xE000, 0xFFFF, 0x10000, 0x10FFFF))
        values = ("", "plain ASCII", "plain ASCII " * 1500,
                  ''.join(chr(value) for value in range(128)), boundaries,
                  '"\\\b\t\n\f\r' * 600, 'plain' * 1500 + boundaries + 'tail' * 1500,
                  *('a' * length + '"🚢\n' for length in (4094, 4095, 4096, 8191)))
        for value in values:
            assert library.render(value) == json.dumps({value: [value, "", value]}, ensure_ascii=ensure_ascii)
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["dict[str, int]", "list[dict[str, int]]"])
def test_sorted_json_without_any_mapping_construction(optimize, annotation):
    check(f'''
        import json

        def value() -> {annotation} | None:
            return None

        def main() -> str:
            return json.dumps(value(), sort_keys=True)
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("options", ["", "ensure_ascii=False", "indent=0", "indent=2",
                                     "indent='→'", "indent=-3", "indent=''",
                                     "separators=(',', ':')", "sort_keys=True",
                                     "indent=2, separators=(' / ', ' = '), sort_keys=True"])
def test_nested_values_options_and_input_order(optimize, options):
    check(f'''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values: dict[str, list[str]] = {{"z": ["é", "😀", "\\n\\t\\b\\f\\r\\x00\\x1f", "\\x7f", "\\\"\\\\"],
                      "a": [], "中": ["<>&'", "line\\u2028separator"]}}
            result = json.dumps(values, {options})
            gc_collect()
            # Sorting must not mutate insertion order or nested values.
            return result + "|" + json.dumps(values) + "|" + json.dumps((1, True, "text", 2.5))
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalars_keys_and_empty_containers(optimize):
    check('''
        import json
        from math import inf, nan

        def main() -> str:
            integers: list[int] = []
            mapping: dict[str, int] = {}
            return (json.dumps(None) + "|" + json.dumps(True) + "|" + json.dumps(False)
                    + "|" + json.dumps(-9223372036854775808) + "|" + json.dumps(integers)
                    + "|" + json.dumps(mapping, indent=2) + "|" + json.dumps(())
                    + "|" + json.dumps({4: "four", -1: "negative", 0: "zero"}, sort_keys=True)
                    + "|" + json.dumps({True: 1, False: 0}, sort_keys=True)
                    + "|" + json.dumps((int(1.5), bool(1), str(2), float(3)))
                    + "|" + json.dumps([0.0, -0.0, 1.5, 1e30, 1e-30, 5e-324, inf, -inf, nan]))
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_flags_indent_and_separators(optimize):
    check('''
        import json

        def render(flag: bool, count: int, token: str, separators: tuple[str, str]) -> str:
            mapping: dict[str, list[int]] = {"b": [1, 2], "a": []}
            nested: list[list[int]] = [[1], []]
            return (json.dumps("é", ensure_ascii=flag)
                    + json.dumps(mapping, indent=count, sort_keys=flag, separators=separators)
                    + json.dumps(nested, indent=token, ensure_ascii=flag))

        def main() -> str:
            return render(True, 2, "--", (",", ":")) + "|" + render(False, -2, "", (", ", ": "))
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("options", ["", "indent=2"])
def test_disallowed_nonfinite_values_are_catchable(optimize, options):
    check(f'''
        import json
        from math import inf, nan
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            result = ""
            for value in [nan, inf, -inf]:
                try:
                    result += json.dumps([value], allow_nan=False, {options})
                except ValueError as error:
                    result += str(error) + "|"
                gc_collect()
                result += json.dumps([1.0])
            return result
    ''', optimize)


@pytest.mark.parametrize("expression", ["iter([1, 2])"])
def test_unsupported_json_shapes_have_located_diagnostics(expression):
    with pytest.raises(LLVMUnsupported, match="LLVM JSON does not support") as caught:
        transpile_llvm(f"import json\ndef main() -> str:\n    return json.dumps({expression})\n")
    assert "at line " in str(caught.value)


@pytest.mark.parametrize("expression", ["{1, 2}", "frozenset({1})", "b'bytes'"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_concrete_unsupported_json_values_raise_when_visited(expression, optimize):
    check(f'''
        import json
        def main() -> str:
            try:
                return json.dumps({expression})
            except TypeError as error:
                return str(error)
    ''', optimize)


@pytest.mark.parametrize("name", ["str", "int", "bool", "float", "list", "tuple", "dict", "object"])
@pytest.mark.parametrize("expression", ["value", "[value]", "{'key': value}"])
def test_json_namesakes_do_not_select_builtin_storage(name, expression):
    check(f'''
            from builtins import str as Text, int as Integer
            import json
            class {name}:
                def __init__(self, rank: Integer):
                    self.rank = rank
            def main() -> Text:
                value = {name}(3)
                try:
                    return json.dumps({expression})
                except TypeError:
                    return "unsupported value"
        ''', 2)


@pytest.mark.parametrize("optimize", [0, 2])
def test_argument_order_and_large_unicode_output(optimize):
    check(dedent('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        def values(events: list[str]) -> dict[str, list[str]]:
            events.append("values")
            return {"body": ["é😀\\n" * 1500], "empty": []}

        def flag(events: list[str]) -> bool:
            events.append("flag")
            gc_collect()
            return False

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            result = json.dumps(values(events), ensure_ascii=flag(events), sort_keys=True)
            gc_collect()
            return json.dumps(events) + result
    '''), optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_variadic_tuples_repeated_aliases_and_portable_numbers(optimize):
    check('''
        import json
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect, gc_set_threshold

        def encode(values: tuple[str, ...]) -> str:
            return json.dumps(values, ensure_ascii=False, indent=True)

        def main() -> str:
            gc_set_threshold(1)
            child = [1, 2]
            aliases = [child, child]
            result = json.dumps(aliases, check_circular=True, skipkeys=True)
            child.append(3)
            result += json.dumps(aliases, check_circular=False)
            gc_collect()
            result += encode(("a", "b", "c"))
            result += json.dumps([int8(128), int8(-129)])
            result += json.dumps((int64(9007199254740993), float32(1.1)))
            return result
    ''', optimize)


@pytest.mark.parametrize("option", ["cls=object", "default=str"])
def test_encoder_callbacks_are_explicitly_unsupported(option):
    with pytest.raises(LLVMUnsupported, match="does not support .* callbacks"):
        transpile_llvm(f"import json\ndef main() -> str:\n    return json.dumps(1, {option})\n")


@pytest.mark.parametrize("expression", ["[None]", "(1, None)"])
def test_none_storage_json(expression):
    LLVM().assert_matches_python(f"import json\ndef main() -> str:\n    return json.dumps({expression})\n")


@pytest.mark.parametrize("name", ["str", "int", "bool", "float", "list", "tuple", "dict", "object"])
def test_namesake_keys_raise_or_skip_at_runtime(name):
    check(f'''
        from builtins import str as Text, int as Integer
        import json
        class {name}:
            def __init__(self, rank: Integer):
                self.rank = rank
        def main() -> Text:
            value = {name}(3)
            result = json.dumps({{value: 1}}, skipkeys=True)
            try:
                json.dumps({{value: 1}})
            except TypeError:
                return result + "|invalid key"
            return "missed error"
    ''', 2)


@pytest.mark.parametrize("expression", ['[[1], ["a"]]'])
def test_union_shapes_have_located_diagnostics(expression):
    with pytest.raises(LLVMUnsupported, match="(unions cannot distinguish|collection views require|keys require).*at line"):
        transpile_llvm(f"import json\ndef main() -> str:\n    return json.dumps({expression})\n")


@pytest.mark.parametrize("expression", ['{"a": 1, "b": "x"}', '[1, "a"]', '[1, 2.5]', '[True, 1]',
                                      '{1: 1, "a": 2}', '{1.5: 3}'])
def test_concrete_union_literals_preserve_json_scalar_kinds(expression):
    comparison = LLVM().assert_matches_python(
        f"import json\ndef main() -> str:\n    return json.dumps({expression})\n",
        sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("expression", ["[]", "{}", "[[]]", '{"a": []}'])
def test_empty_literals_explain_missing_item_type(expression):
    with pytest.raises(LLVMUnsupported, match="annotate the container.*at line"):
        transpile_llvm(f"import json\ndef main() -> str:\n    return json.dumps({expression})\n")


@pytest.mark.parametrize("method", [False, True])
@pytest.mark.parametrize("expression", ["[]", "{}", "[[]]", '{"a": []}'])
def test_preparation_diagnostics_retain_original_function_and_method_locations(method, expression):
    declaration = ("class Encoder:\n    def render(self) -> str:\n        " if method
                   else "\ndef render() -> str:\n    ")
    invocation = "Encoder().render()" if method else "render()"
    source = (f"import json\n\n{declaration}return json.dumps({expression})\n\n"
              f"def main() -> str:\n    return {invocation}\n")
    with pytest.raises(LLVMUnsupported, match="annotate the container") as caught:
        transpile_llvm(source, filename="empty_native.py")
    column = 16 if method else 12
    assert caught.value.__notes__ == [
        f"Source location: empty_native.py:5:{column} "
        "(render; reported line above is function-relative)",
    ]


def test_unreached_empty_literal_does_not_override_typed_sibling_context(tmp_path):
    result = LLVM().assert_matches_python('''
import json
def unused() -> str:
    return json.dumps([])
def main() -> str:
    values: list[list[list[int]]] = [[[]], [[1]]]
    return json.dumps(values)
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["int", "bool", "Box", "list", "dict", '{"a": int}',
                                      "[bool]", "(1, Box)", "{int: 1}"])
def test_class_objects_are_rejected_without_requesting_new_analysis(expression):
    with pytest.raises(LLVMUnsupported, match="does not support class objects.*at line"):
        transpile_llvm(f"import json\nclass Box: pass\ndef main() -> str:\n    return json.dumps({expression})\n")


def test_object_value_does_not_receive_empty_container_hint():
    with pytest.raises(LLVMUnsupported, match="does not support object.*at line") as caught:
        transpile_llvm("import json\ndef main() -> str:\n    return json.dumps(object())\n")
    assert "annotate" not in str(caught.value)


def test_library_repeated_calls_keep_results_independent(tmp_path):
    library = LLVM().compile_library('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        def render(values: list[str], ascii: bool) -> str:
            gc_set_threshold(1)
            result = json.dumps(obj=values, ensure_ascii=ascii, cls=None, default=None)
            gc_collect()
            return result
    ''', tmp_path, entry_point="render")
    import json

    results = []
    for index in range(30):
        values = ["é😀\\\"" * (index * 30), str(index)]
        results.append(library.render(values, bool(index % 2)))
        assert results[-1] == json.dumps(values, ensure_ascii=bool(index % 2))
    assert results[0] == '["", "0"]'


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("formatter", ["json.dumps", "repr"])
def test_repeated_buffered_formatters_release_scratch(tmp_path, managed, formatter):
    source = f'''
        import json
        from pyjs.native import gc_set_threshold

        def main() -> str:
            {"gc_set_threshold(1000)" if managed else "pass"}
            total = 0
            for index in range(100000):
                total += len({formatter}([index]))
            return str(total)
    '''
    executable = LLVM().compile(transpile_llvm(source), tmp_path)
    # A deterministic upper bound, not a timing/RSS threshold: the old 4 KiB
    # scratch retention needs over 400 MiB, while result-sized arena storage
    # (or the managed heap) fits comfortably here. ASan reserves huge virtual
    # ranges, so this specific bounded-process check is unsanitized.
    result = subprocess.run([sys.executable, "-c", '''
import os, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (128 * 1024**2, 128 * 1024**2))
os.execv(sys.argv[1], [sys.argv[1]])
''', str(executable)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(sum(len(f"[{index}]") for index in range(100000)))


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_json_allocation_failure_releases_scratch_and_recovers(tmp_path, managed, optimize):
    source = f'''
        import json
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        def main() -> int:
            {"gc_set_threshold(1)" if managed else "pass"}
            values = {{"b": ["é" * 5000], "a": ["text"]}}
            expected = json.dumps(values, sort_keys=True, indent=2)
            failures = 0
            for attempt in range(1, 100):
                complete = False
                try:
                    arm(attempt)
                    result = json.dumps(values, sort_keys=True, indent=2)
                    arm(0)
                    assert result == expected
                    complete = True
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                {"gc_collect()" if managed else "pass"}
                assert json.dumps(values, sort_keys=True, indent=2) == expected
                if complete:
                    return 0 if failures else 1
            return 2
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("options", ["", ", indent=4096"])
def test_write_failure_precedes_later_invalid_float(tmp_path, optimize, options):
    source = f'''
        import json
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        def main() -> int:
            gc_set_threshold(1)
            values = ("x" * 10000, float("nan"))
            # Count output reallocations only, not traversal-frame/map setup:
            # fail the opening buffer and its next growth before the later NaN.
            for attempt in [1, 2]:
                try:
                    arm(attempt)
                    json.dumps(values, allow_nan=False{options})
                    return 1
                except MemoryError:
                    arm(0)
                except ValueError:
                    arm(0)
                    return 2
                finally:
                    arm(0)
                gc_collect()
                assert json.dumps([1]) == "[1]"
            try:
                json.dumps(values, allow_nan=False{options})
            except ValueError:
                return 0
            return 3
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize, only=("realloc",))
