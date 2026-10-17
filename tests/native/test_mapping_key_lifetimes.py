import pytest

from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError

SOURCE = '''
from pyjs.native import gc_collect
class Key:
    def __init__(self, number: int):
        self.number = number
    def __hash__(self) -> int:
        return self.number
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Key) and self.number == other.number

OBJECTS: list[dict[Key, int]] = []
TUPLES: list[dict[tuple[tuple[Key, int], int], int]] = []
STRINGS: list[dict[str, int]] = []

def put(mapping: dict[Key, int], key: Key, value: int) -> None:
    mapping.__setitem__(key, value)

def render(number: int, fail: bool) -> str:
    objects: dict[Key, int] = {}
    tuples: dict[tuple[tuple[Key, int], int], int] = {}
    strings: dict[str, int] = {}
    INSERT
    OBJECTS.append(objects)
    TUPLES.append(tuples)
    STRINGS.append(strings)
    junk = [Key(999) for _ in range(64)]
    gc_collect()
    if fail:
        raise ValueError("saved keys before failure")
    return (repr([key.number for mapping in OBJECTS for key in mapping])
            + repr([(key[0][0].number, key[0][1], key[1]) for mapping in TUPLES for key in mapping])
            + repr([key for mapping in STRINGS for key in mapping])
            + str(len(junk)))
'''


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("explicit", [False, True], ids=["subscription", "dunder"])
def test_inserted_keys_survive_library_calls_and_failed_calls(tmp_path, optimize, explicit):
    entries = [("objects", "Key(number)"), ("tuples", "((Key(number + 10), number), number)"),
               ("strings", '"str-" + str(number)')]
    insertion = "\n    ".join(
        (f"put({name}, {key}, number)" if name == "objects" else f"{name}.__setitem__({key}, number)")
        if explicit else f"{name}[{key}] = number"
        for name, key in entries
    )
    source = SOURCE.replace("INSERT", insertion)
    namespace = {}
    exec(source, namespace)
    arguments = [(1, False), (2, True), (3, False), (4, False)]
    expected = []
    for number, fail in arguments:
        if fail:
            with pytest.raises(ValueError, match="saved keys before failure"):
                namespace["render"](number, fail)
        else:
            expected.append(namespace["render"](number, fail))

    # Each library call discards its request arena. A single executable call
    # can hide LOCAL keys incorrectly retained in an escaping dictionary.
    # Int-only keys deliberately expose arena reuse: the earlier string-field
    # shape happened to retain readable data even on the broken base revision.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number, fail in arguments:
            if fail:
                with pytest.raises(LLVMRuntimeError, match="saved keys before failure"):
                    library.render(number, fail)
            else:
                actual.append(library.render(number, fail))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()
