import pytest

from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_dict_store_does_not_acquire_builtin_key_callbacks(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect
        class Key:
            def __hash__(self) -> int:
                raise ValueError("application storage must not hash")
        class dict:
            def __init__(self):
                self.key: Key | None = None
            def __setitem__(self, key: Key, value: int) -> None:
                gc_collect()
                self.key = key
        def main() -> str:
            mapping = dict()
            key = Key()
            mapping[key] = 1
            mapping.__setitem__(key, 2)
            gc_collect()
            return str(mapping.key is key)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", [False, True], ids=["assignment", "explicit-dunder"])
@pytest.mark.parametrize("callback", ["hash", "equal", "other"])
def test_mapping_stores_retain_virtual_callback_operands_across_requests(tmp_path, optimize, method, callback):
    store = "mapping.__setitem__((0, key), payload)" if method else "mapping[(0, key)] = payload"
    source = f'''
from pyjs.native import gc_collect
class Key:
    def __init__(self, number: int, fail: bool):
        self.number = number
        self.fail = fail
    def __hash__(self) -> int:
        return 1
    def __eq__(self, other: Key) -> bool:
        return False
    def save(self) -> None:
        SAVED.append(self)
        gc_collect()
        if self.fail:
            raise ValueError("saved during store")
class Saving(Key):
    def __hash__(self) -> int:
        {"self.save()" if callback == "hash" else "pass"}
        return 1
    def __eq__(self, other: Key) -> bool:
        {"self.save()" if callback == "equal" else "other.save()" if callback == "other" else "pass"}
        return False
SAVED: list[Key] = []
def store(mapping: dict[tuple[int, Key], list[int]], key: Key, payload: list[int]) -> None:
    {store}
def render(number: int, fail: bool) -> str:
    mapping: dict[tuple[int, Key], list[int]] = {{}}
    first, second = Saving(number, fail), Saving(-number, fail)
    store(mapping, first, [number])
    store(mapping, second, [-number])
    junk = [Key(999, False) for _ in range(40)]
    gc_collect()
    return str((len(mapping), [key.number for key in SAVED], len(junk)))
'''
    namespace = {}
    exec(source, namespace)
    requests = [(1, False), (2, True), (3, False), (4, False)]
    expected = []
    for arguments in requests:
        if arguments[1]:
            with pytest.raises(ValueError, match="saved during store"):
                namespace["render"](*arguments)
        else:
            expected.append(namespace["render"](*arguments))
    # A retained key must survive request-arena reset, not just remain readable
    # before the process exits. The ctypes library is deliberately unsanitized.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for arguments in requests:
            if arguments[1]:
                with pytest.raises(LLVMRuntimeError, match="saved during store"):
                    library.render(*arguments)
            else:
                actual.append(library.render(*arguments))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()
