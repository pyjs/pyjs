import pytest

from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.semantics.helpers import run_python

MANAGER = '''
from pyjs.native import gc_collect, gc_set_threshold

class Swallow:
    def __enter__(self) -> None: pass
    def __exit__(self, kind: object, value: object, trace: object) -> bool:
        gc_collect()
        return True

class Box:
    def __init__(self, value: int):
        self.value = value
'''


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,value", [
    ("int", "7"), ("float", "2.5"), ("bool", "True"),
    ("str", "'text'"), ("list[int]", "[3]"), ("Box", "Box(5)"),
    ("list[int] | str", "[3]"),
])
def test_suppressed_return_enforces_nonoptional_contract(tmp_path, optimize, annotation, value):
    source = MANAGER + f'''
def make(fail: bool) -> {annotation}:
    if fail:
        raise ValueError("suppressed")
    return {value}

def broken(fail: bool) -> {annotation}:
    with Swallow():
        return make(fail)

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    for fail in [False, True, False, True]:
        try:
            result = broken(fail)
            events.append("value")
        except TypeError as error:
            events.append(str(error))
        finally:
            gc_collect()
            events.append("cleanup")
    return "|".join(events)
'''
    # CPython does not enforce annotations. Only the oracle gets an explicit
    # check: adding it to the compiled source would hide a missing native guard.
    oracle = source.replace(
        "            result = broken(fail)\n",
        '            result = broken(fail)\n'
        '            if result is None:\n'
        '                raise TypeError("broken returned None through a non-optional result contract")\n',
    )
    expected = run_python(oracle + '\nprint(main(), end="")\n')
    actual = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert expected.returncode == actual.returncode == 0
    assert actual.stdout == expected.stdout
    assert expected.stderr == actual.stderr == ""


def test_suppressed_return_reports_the_function_and_caller(tmp_path):
    source = '''
class Swallow:
    def __enter__(self) -> None: pass
    def __exit__(self, kind: object, value: object, trace: object) -> bool:
        return True

def broken() -> list[int]:
    with Swallow():
        raise ValueError("suppressed")
        return [1]

def main() -> int:
    return len(broken())
'''
    result = LLVM().run_source(source, filename="missing_return.py", directory=tmp_path)
    assert result.returncode < 0
    assert result.stdout == ""
    assert result.stderr == (
        "Traceback (native PyJS):\n"
        '  File "missing_return.py", line 13, in main\n'
        '  File "missing_return.py", line 7, in broken\n'
        "TypeError: broken returned None through a non-optional result contract\n"
    )


def test_library_recovers_after_suppressed_return_contract_failure(tmp_path):
    source = MANAGER + '''
def make(fail: bool) -> str:
    if fail:
        raise ValueError("suppressed")
    return "ready"

def render(fail: bool) -> str:
    gc_set_threshold(1)
    with Swallow():
        return make(fail)
'''
    library = LLVM().compile_library(source, tmp_path, entry_point="render")
    try:
        for _ in range(3):
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render(True)
            assert caught.value.exception_type == "TypeError"
            assert str(caught.value) == "render returned None through a non-optional result contract"
            assert library.render(False) == "ready"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,value", [
    ("int | None", "7"), ("list[int] | None", "[3]"),
    ("list[int] | str | None", "[3]"), ("object", "[3]"),
])
def test_suppressed_return_accepts_nullable_and_erased_contracts(tmp_path, optimize, annotation, value):
    result = LLVM().assert_matches_python(MANAGER + f'''
def make(fail: bool) -> {annotation}:
    if fail:
        raise ValueError("suppressed")
    return {value}

def nullable(fail: bool) -> {annotation}:
    with Swallow():
        return make(fail)

def main() -> str:
    gc_set_threshold(1)
    return str(nullable(False) is None) + ":" + str(nullable(True) is None)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
