import sys
import typing
from types import ModuleType

import pytest

from pyjs.analysis.source import create_module
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError

SOURCE = '''
from pyjs import llvm
from pyjs.web.domx import div
from pyjs.web.ssr import write_html_fd

HISTORY: list[str] = []

@llvm.inline("icmp eq i1 true, true")
def native() -> bool:
    return False

@llvm.inline("add i64 0, 0")
def interrupt() -> int:
    raise KeyboardInterrupt("comparison interrupted")

def render(mode: int) -> str:
    HISTORY.append("retained" * 4096)
    if mode == 1 and not native():
        raise ValueError("Python rendering failed")
    if mode == 2 and native():
        raise ValueError("Native rendering failed")
    if mode == 4:
        interrupt()
    return "native" if mode == 3 and native() else "same"

def write(mode: int, descriptor: int) -> int:
    if mode == 5:
        return 5
    return write_html_fd(div(render(mode)), descriptor)
'''


def library_in_traceback(error):
    # Retaining a failed comparison's traceback is the real lifetime hazard:
    # its frame owns the library even when the caller never received a result.
    traceback = error.__traceback__
    while traceback is not None:
        local = traceback.tb_frame.f_locals
        if traceback.tb_frame.f_code.co_name == "compare_library_with_python":
            return local["library"]
        if (
            traceback.tb_frame.f_code.co_name == "assert_library_matches_python"
            and "comparison" in local
        ):
            return local["comparison"].library
        traceback = traceback.tb_next
    raise AssertionError("comparison library was not retained by the traceback")


@pytest.mark.parametrize("mode,error,direct", [
    (1, ValueError, False), (2, LLVMRuntimeError, False),
    (3, AssertionError, False), (4, KeyboardInterrupt, False),
    (1, ValueError, True), (2, LLVMRuntimeError, True),
    (3, AssertionError, True), (4, KeyboardInterrupt, True),
    (5, OSError, True),
])
def test_failed_comparison_closes_real_library_while_traceback_is_retained(tmp_path, mode, error, direct):
    with pytest.raises(error) as caught:
        LLVM().assert_library_matches_python(
            SOURCE, mode, directory=tmp_path,
            entry_point="write" if direct else "render", direct=direct,
        )
    library = library_in_traceback(caught.value)
    try:
        assert library.managed
        with pytest.raises(RuntimeError, match="library is closed"):
            library.render(0)
    finally:
        library.close()


@pytest.mark.parametrize("stage", ["equality", "truth", "repr"])
@pytest.mark.parametrize("failure", [ValueError, KeyboardInterrupt])
def test_asserting_comparison_closes_library_when_result_protocol_raises(tmp_path, stage, failure):
    class Truth:
        def __bool__(self):
            raise failure("comparison truth failed")

    class Text(str):
        def __eq__(self, other):
            if stage == "equality":
                raise failure("comparison equality failed")
            return Truth() if stage == "truth" else False

        def __repr__(self):
            raise failure("comparison repr failed")

    with pytest.raises(failure, match=f"comparison {stage} failed") as caught:
        LLVM().assert_library_matches_python('''
            from pyjs.native import gc_collect
            def main(text: str) -> str:
                gc_collect()
                return text
        ''', Text("hello"), directory=tmp_path)
    library = library_in_traceback(caught.value)
    try:
        assert library.managed and library._heap is None
        with pytest.raises(RuntimeError, match="library is closed"):
            library.render("retry")
    finally:
        library.close()


@pytest.mark.parametrize("existing", ["absent", "module", "blocked"])
def test_failed_python_module_initialization_closes_library_and_restores_registry(tmp_path, existing):
    module_name = "llvm_failed_python_initialization"
    python_name = module_name + "_python"
    was_registered = python_name in sys.modules
    previous = sys.modules.get(python_name)
    sentinel = ModuleType(python_name) if existing == "module" else None
    if existing != "absent":
        sys.modules[python_name] = sentinel
    else:
        sys.modules.pop(python_name, None)
    try:
        with pytest.raises(ValueError, match="Python initialization failed") as caught:
            LLVM().compare_library_with_python(
                SOURCE + '''
if __name__.endswith("_python"):
    raise ValueError("Python initialization failed")
''', 0, directory=tmp_path, entry_point="render", module_name=module_name,
            )
        library = library_in_traceback(caught.value)
        try:
            assert sys.modules.get(python_name) is sentinel
            assert (python_name in sys.modules) == (existing != "absent")
            with pytest.raises(RuntimeError, match="library is closed"):
                library.render(0)
        finally:
            library.close()
    finally:
        if was_registered:
            sys.modules[python_name] = previous
        else:
            sys.modules.pop(python_name, None)


def test_success_and_nonasserting_mismatch_transfer_library_ownership(tmp_path):
    llvm = LLVM()
    for mode in (0, 3):
        comparison = llvm.compare_library_with_python(
            SOURCE, mode, directory=tmp_path / str(mode), entry_point="render",
        )
        try:
            assert comparison.matches == (mode == 0)
            assert comparison.library.render(0) == "same"
        finally:
            comparison.library.close()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_comparison_restores_overloads_for_reused_module_names(tmp_path, existing, fail):
    module_name = "llvm_overload_comparison"
    python_name = module_name + "_python"
    registry = vars(typing)["_overload_registry"]
    was_registered = python_name in sys.modules
    previous = sys.modules.get(python_name)
    previous_overloads = registry.get(python_name)
    original = None
    if existing:
        original = create_module('''
from typing import overload

@overload
def choose(value: str) -> str: ...

def choose(value: str) -> str:
    return value
''', "original_overloads.py", python_name)
        overloads = typing.get_overloads(original.choose)
    else:
        sys.modules.pop(python_name, None)
        registry.pop(python_name, None)
    source = SOURCE + '''
from typing import overload

@overload
def choose(value: int) -> str: ...

def choose(value: int) -> str:
    return str(value)
'''
    try:
        if fail:
            with pytest.raises(ValueError, match="Python rendering failed"):
                LLVM().compare_library_with_python(
                    source, 1, directory=tmp_path / "comparison",
                    module_name=module_name, entry_point="render",
                )
        else:
            comparison = LLVM().compare_library_with_python(
                source, 0, directory=tmp_path / "comparison",
                module_name=module_name, entry_point="render",
            )
            comparison.library.close()
        if original is not None:
            assert sys.modules[python_name] is original
            assert typing.get_overloads(original.choose) == overloads
            result = LLVM().run_source(f'''
                from {python_name} import choose

                def main() -> int:
                    return len(choose("okay")) - 4
            ''', directory=tmp_path / "reuse")
            assert result.returncode == 0, result.stderr
        else:
            assert python_name not in sys.modules
            assert python_name not in registry
    finally:
        sys.modules.pop(python_name, None)
        registry.pop(python_name, None)
        if was_registered:
            sys.modules[python_name] = previous
        if previous_overloads is not None:
            registry[python_name] = previous_overloads
