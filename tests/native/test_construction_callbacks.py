import pytest

from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("construction", [
    "{(0, first), (0, second)}",
    "{(0, first): 1, (0, second): 2}",
    "set([(0, first), (0, second)])",
    "{(0, key) for key in [first, second]}",
    "{(0, key): 1 for key in [first, second]}",
    "{*[(0, first), (0, second)]}",
    "{(0, first), *[(0, second)]}",
    "{**empty, (0, first): 1, (0, second): 2}",
    "{" + ", ".join(["(0, first)"] * 30 + ["(0, second)"]) + "}",
    "{" + ", ".join(["(0, first): 1"] * 34 + ["(0, second): 2"]) + "}",
])
@pytest.mark.parametrize("callback", ["hash", "equal", "other"])
def test_construction_callbacks_retain_keys_across_requests(tmp_path, optimize, construction, callback):
    source = f'''
from pyjs.native import gc_collect
class Key:
    def __init__(self, number: int, fail: bool):
        self.number = number
        self.fail = fail
    def __hash__(self) -> int:
        {"self.save()" if callback == "hash" else "pass"}
        return 1
    def __eq__(self, other: Key) -> bool:
        {"self.save()" if callback == "equal" else "other.save()" if callback == "other" else "pass"}
        return self.number == other.number
    def save(self) -> None:
        SAVED.append(self)
        gc_collect()
        if self.fail:
            raise ValueError("saved during construction")
SAVED: list[Key] = []
def render(number: int, fail: bool) -> str:
    first, second = Key(number, fail), Key(-number, fail)
    empty: dict[tuple[int, Key], int] = {{}}
    values = {construction}
    # Do not compare the resulting collection: comparison retention could
    # accidentally hide the construction-only ownership defect.
    junk = [Key(999, False) for _ in range(32)]
    gc_collect()
    return str((len(values), [key.number for key in SAVED], len(junk)))
'''
    namespace = {}
    exec(source, namespace)
    requests = [(1, False), (2, True), (3, False), (4, False)]
    expected = []
    for arguments in requests:
        if arguments[1]:
            with pytest.raises(ValueError, match="saved during construction"):
                namespace["render"](*arguments)
        else:
            expected.append(namespace["render"](*arguments))
    # Request-arena reset is essential to this regression. A standalone
    # sanitizer process can leave dangling saved objects readable until exit.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for arguments in requests:
            if arguments[1]:
                with pytest.raises(LLVMRuntimeError, match="saved during construction"):
                    library.render(*arguments)
            else:
                actual.append(library.render(*arguments))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()
