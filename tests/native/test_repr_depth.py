import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_deep_repr_raises_and_subsequent_formatting_recovers(tmp_path, optimize):
    # Native formatting counts active containers; CPython's recursion budget
    # also depends on interpreter version and the embedding process's limit.
    result = LLVM().run_source('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        type Value = str | list[Value] | dict[str, Value]

        def render(value: Value, mode: int) -> str:
            if mode == 0:
                return repr(value)
            if mode == 1:
                return str(value)
            if mode == 2:
                return f"{value!r}"
            if mode == 3:
                return "|".join(map(lambda item: str(item), [value]))
            if mode == 4:
                formatter: Callable[[Value], str] = lambda item: repr(item)
                return formatter(value)
            return format(value)

        def main() -> int:
            gc_set_threshold(64)
            deep: Value = "leaf"
            for index in range(1600):
                deep = {"nested": [deep]}
            shallow: list[Value] = ["quoted'✓"]
            shallow.append(shallow)
            for mode in range(6):
                saved = "unchanged"
                try:
                    saved = render(deep, mode)
                except RecursionError:
                    gc_collect()
                    print("caught", saved)
                print(render(shallow, mode))
            try:
                print(deep)
            except RecursionError:
                gc_collect()
                print("print caught")
            print(repr(shallow))
            return 0
    ''', directory=tmp_path, optimize=optimize)
    assert result.returncode == 0, result.stderr
    shallow = ["quoted'✓"]
    shallow.append(shallow)
    assert result.stdout == (
        ("caught unchanged\n" + repr(shallow) + "\n") * 6
        + "print caught\n" + repr(shallow) + "\n"
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_native_repr_depth_boundary_preserves_cycle_shortcuts(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold

        type Node = list[Node]

        def main() -> int:
            gc_set_threshold(64)
            root: Node = []
            tail = root
            for index in range(999):
                child: Node = []
                tail.append(child)
                tail = child
            if len(repr(root)) != 2000:
                return 1
            tail.append(root)
            if len(repr(root)) != 2005:
                return 2
            # The repeated root succeeds at the limit, but a fresh nonempty
            # child must fail without linking a frame that needs unwinding.
            tail.clear()
            tail.append([[]])
            saved = "unchanged"
            caught = False
            try:
                saved = repr(root)
            except RecursionError:
                caught = True
            gc_collect()
            if not caught or saved != "unchanged":
                return 3
            tail.clear()
            if len(repr(root)) != 2000:
                return 4
            return 0
    '''
    result = LLVM().run_source(source, directory=tmp_path, optimize=optimize)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_depth_failure_preserves_enclosing_cycle_scope(tmp_path, optimize):
    result = LLVM().run_source('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, child: list[Item]):
                self.child = child

            def __repr__(self) -> str:
                return repr(self.child)

        class Probe:
            def __init__(self, deep: list[Item]):
                self.deep = deep
                self.owner: list[Probe] = []

            def __repr__(self) -> str:
                try:
                    repr(self.deep)
                except RecursionError:
                    gc_collect()
                    return repr(self.owner)
                return "missing depth check"

        def main() -> int:
            gc_set_threshold(64)
            deep: list[Item] = []
            for index in range(1200):
                deep = [Item(deep)]
            probe = Probe(deep)
            probe.owner = [probe]
            for step in range(4):
                print(repr(probe.owner))
            return 0
    ''', directory=tmp_path, optimize=optimize)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "[[...]]\n" * 4


@pytest.mark.parametrize("optimize", [0, 2])
def test_map_formatter_prepares_depth_error_and_reports_caller(tmp_path, optimize):
    result = LLVM().run_source('''type Node = list[Node]

def main() -> str:
    value: Node = []
    for step in range(1100):
        value = [value]
    return "|".join(map(lambda item: str(item), [value]))
''', filename="map_depth.py", directory=tmp_path, optimize=optimize)
    assert result.returncode != 0
    assert result.stderr == (
        'Traceback (native PyJS):\n'
        '  File "map_depth.py", line 7, in main\n'
        '  File "map_depth.py", line 7, in iterator_step.0\n'
        '  File "map_depth.py", line 7, in lambda.0\n'
        'RecursionError: maximum recursion depth exceeded while getting the repr of an object\n'
    )
