import signal
import subprocess
import sys
import textwrap

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import TEXT_EDIT_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_text_edit_contract(optimize):
    result = LLVM().assert_matches_python(TEXT_EDIT_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0


@pytest.mark.parametrize("optimize", [0, 2])
def test_log_processing_preserves_split_lists_and_text_across_collection(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def normalize(value: str) -> str:
            return value.strip().replace("warn", "warning").upper()

        def main() -> str:
            gc_set_threshold(1)
            report = ""
            for line in " info: café :ready \\n warn: 😀 : retry\\0 ".split("\\n"):
                fields = line.split(":")
                gc_collect()
                fields.append("extra")
                fields.append("forces growth")
                gc_collect()
                for field in fields:
                    value = normalize(field)
                    report += value[::2] + value[::-1] + "|"
                    gc_collect()
                report += "é😀".join(fields)
            return report
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_invalid_text_operations_trap_instead_of_invalid_memory_access(optimize):
    for expression in ('"abc"[::0]', '"abc"[99]', '"".split("")', '"ab" * 9223372036854775807'):
        source = f"def main() -> int: return len({expression})"
        result = LLVM().run_source(source, optimize=optimize)
        assert result.returncode in {-signal.SIGILL, -signal.SIGTRAP}, result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_join_other_concrete_iterables(optimize):
    LLVM().assert_matches_python('def main() -> str: return ",".join(("a", "b"))', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_join_evaluates_separator_and_preserves_typed_lists(optimize):
    LLVM().assert_matches_python('''
        def separator(events: list[str]) -> str:
            events.append("called")
            return ","

        def main() -> str:
            events: list[str] = []
            empty = separator(events).join([])
            typed: list[str] = []
            empty += separator(events).join(typed)
            return empty + "|".join(events) + "|".join(["one"])
    ''', optimize=optimize)


def test_untyped_list_outside_empty_join_has_a_focused_diagnostic():
    with pytest.raises(LLVMUnsupported, match="has no concrete item type"):
        transpile_llvm('def main() -> int: return len([])')


def test_string_edits_without_splitting_do_not_link_list_allocation():
    output = transpile_llvm('def main() -> str: return "é😀"[::-1]')
    assert "@pyjs.list.new.owned" not in output
    assert "@pyjs.unicode." not in output


@pytest.mark.parametrize("optimize", [0, 2])
def test_list_storage_rejects_invalid_sizes_before_dereferencing_its_owner(tmp_path, optimize):
    library = LLVM().compile(transpile_llvm('def main() -> int: return len([1])'),
                             tmp_path, shared=True, optimize=optimize)
    for item_size, length in ((0, 0), (-1, 0), (8, -1), (8, 9223372036854775807)):
        result = subprocess.run([sys.executable, "-c", textwrap.dedent(f'''
            import ctypes
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            library = ctypes.CDLL({str(library)!r})
            create = getattr(library, "pyjs.list.new.owned")
            create.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_int64] * 2
            create.restype = ctypes.c_void_p
            assert create(None, None, None, {item_size}, {length}) is None
        ''')], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
