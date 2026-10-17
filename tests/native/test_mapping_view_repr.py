import pytest

from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("expression", ["repr(view)", "view.__repr__()", 'f"{view!r}"', "format(view)"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_view_formatting_can_pin_nested_members(tmp_path, optimize, expression):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_count, gc_pin, gc_unpin

        class Label:
            def __init__(self, value: int):
                self.value = value

            def __repr__(self) -> str:
                gc_pin(self)
                gc_collect()
                return str(self.value)

        def main() -> str:
            data = {{1: [Label(7)], 2: [Label(9)]}}
            view = data.values()
            result = {expression}
            gc_collect()
            result += ":" + str(gc_count())
            for values in view:
                for value in values:
                    gc_unpin(value)
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_view_repr_retention_survives_requests_and_failure(tmp_path, optimize):
    source = '''
from pyjs.native import gc_collect
class Label:
    def __init__(self, number: int, fail: bool):
        self.number = number
        self.fail = fail
    def __repr__(self) -> str:
        SAVED.append(self)
        gc_collect()
        if self.fail:
            raise ValueError("saved before failure")
        return str(self.number)
SAVED: list[Label] = []
def render(number: int, fail: bool) -> str:
    data = {number: Label(number, fail)}
    text = repr(data.values())
    gc_collect()
    return text + ":" + str([value.number for value in SAVED])
'''
    namespace = {}
    exec(source, namespace)
    expected = []
    requests = [(1, False), (2, True), (3, False), (4, False)]
    for number, fail in requests:
        if fail:
            with pytest.raises(ValueError, match="saved before failure"):
                namespace["render"](number, fail)
        else:
            expected.append(namespace["render"](number, fail))
    # ctypes libraries are unsanitized; standalone formatting tests use ASan/UBSan.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number, fail in requests:
            if fail:
                with pytest.raises(LLVMRuntimeError, match="saved before failure"):
                    library.render(number, fail)
            else:
                actual.append(library.render(number, fail))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()
