"""Member dispatch must join Python values, not merely equal LLVM layouts."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("access", ["method", "property", "field"])
@pytest.mark.parametrize("annotation, first, second", [
    ("str", '"typed" + str(1)', '"typed" + str(2)'),
    ("list[str]", '["first"]', '["second"]'),
    ("str | int", '"typed"', "7"),
    ("str | int", "True", "False"),
    ("int | None", "7", "None"),
    ("list[str] | None", '["retained"]', "None"),
    ("list[int8]", "[int8(-1)]", "[int8(127)]"),
], ids=["string", "list", "tagged", "tagged-bool", "optional-int", "optional-list", "represented-list"])
def test_member_results_join_object(tmp_path, optimize, access, annotation, first, second):
    source = '''
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold

class Typed:
    def __init__(self, state: bool):
        self.saved: ANNOTATION = FIRST if state else SECOND
    DECORATOR
    def value(self) -> ANNOTATION:
        gc_collect()
        return self.saved

class Erased:
    def __init__(self):
        self.padding = 42
        self.saved: object = "erased"
    DECORATOR
    def value(self) -> object:
        gc_collect()
        return self.saved

def read(item: Typed | Erased) -> object:
    return ACCESS

def main() -> str:
    gc_set_threshold(1)
    items: list[Typed | Erased] = [Typed(True), Typed(False), Erased()]
    values: list[object] = []
    for item in items:
        values.append(read(item))
    items.clear()
    gc_collect()
    return repr(values)
'''.replace("ANNOTATION", annotation).replace("FIRST", first).replace("SECOND", second)
    source = source.replace("DECORATOR", "@property" if access == "property" else "")
    source = source.replace("ACCESS", {"method": "item.value()", "property": "item.value",
                                       "field": "item.saved"}[access])
    comparison = LLVM().assert_matches_python(
        source, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"),
    )
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("access", ["method", "property", "field"])
@pytest.mark.parametrize("annotation", ["list[int8]", "list[int8] | str", "list[int8] | None"])
def test_joined_reference_keeps_identity_and_declared_layout(tmp_path, optimize, access, annotation):
    source = '''
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold

class Typed:
    def __init__(self, value: list[int8]):
        self.saved: ANNOTATION = value
    DECORATOR
    def value(self) -> ANNOTATION:
        gc_collect()
        return self.saved

class Erased:
    def __init__(self, value: object):
        self.saved = value
    DECORATOR
    def value(self) -> object:
        gc_collect()
        return self.saved

def read(item: Typed | Erased) -> object:
    return ACCESS

def main() -> str:
    gc_set_threshold(1)
    original = [int8(-1), int8(127)]
    items: list[Typed | Erased] = [Typed(original), Erased(original)]
    result = ""
    for item in items:
        value = read(item)
        gc_collect()
        alias = cast(list[int8], value)
        alias[0] += int8(1)
        result += str(alias is original) + repr(alias)
    return result + repr(original)
'''.replace("DECORATOR", "@property" if access == "property" else "").replace("ANNOTATION", annotation)
    source = source.replace("ACCESS", {"method": "item.value()", "property": "item.value",
                                       "field": "item.saved"}[access])
    comparison = LLVM().assert_matches_python(
        source, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"),
    )
    assert comparison.native.stdout == "True[0, 127]True[1, 127][1, 127]"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("access", ["method", "property", "field"])
def test_member_join_does_not_implicitly_erase_portable_scalar(access):
    source = '''
from pyjs import int8
class Typed:
    def __init__(self):
        self.saved = int8(7)
    DECORATOR
    def value(self) -> int8:
        return self.saved
class Erased:
    def __init__(self):
        self.saved: object = 7
    DECORATOR
    def value(self) -> object:
        return self.saved
def read(item: Typed | Erased) -> object:
    return ACCESS
def main() -> int:
    values = [read(Typed()), read(Erased())]
    return len(values)
'''.replace("DECORATOR", "@property" if access == "property" else "")
    source = source.replace("ACCESS", {"method": "item.value()", "property": "item.value",
                                       "field": "item.saved"}[access])
    with pytest.raises((CompilationError, LLVMUnsupported), match="represent|explicit int"):
        transpile_llvm(source)
