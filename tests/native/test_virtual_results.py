import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_covariant_virtual_results_keep_direct_and_captured_abis(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def read(self, events: list[str], fail: bool = False) -> int | None:
                events.append("base")
                return None

            @property
            def value(self) -> list[str] | str:
                return "base"

        class Child(Base):
            def read(self, events: list[str], fail: bool = False) -> int:
                events.append("child")
                gc_collect()
                if fail:
                    raise ValueError("retry")
                return 42

            @property
            def value(self) -> list[str]:
                gc_collect()
                return ["child"]

        class Empty(Base):
            def read(self, events: list[str], fail: bool = False) -> None:
                events.append("empty")
                gc_collect()

        class Grandchild(Child):
            def read(self, events: list[str], fail: bool = False) -> int:
                events.append("grandchild")
                return super().read(events, fail) + 1

        def capture(value: Base) -> Callable[[list[str], bool], int | None]:
            return value.read

        def exercise(value: Base, events: list[str]) -> str:
            callback = capture(value)
            first = value.read(events)
            field = value.value
            gc_collect()
            second = callback(events, False)
            try:
                value.read(events, True)
            except ValueError as error:
                events.append(str(error))
            gc_collect()
            return repr((first, second, value.read(events), field))

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values: list[Base] = [Base(), Child(), Empty(), Grandchild()]
            outcomes = [exercise(value, events) for value in values]
            return repr((outcomes, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("nested", [False, True])
def test_virtual_tuple_results_preserve_existing_layout_views(tmp_path, optimize, nested):
    base = "list[tuple[int, int]]" if nested else "tuple[int, int]"
    derived = "list[tuple[int, ...]]" if nested else "tuple[int, ...]"
    value = "[(9, 3)]" if nested else "(9, 3)"
    comparison = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def read(self) -> {base}:
                return {value}

        class Child(Base):
            def read(self) -> {derived}:
                gc_collect()
                return {value}

        def main() -> str:
            gc_set_threshold(1)
            value: Base = Child()
            first = value.read()
            gc_collect()
            return repr((first, value.read()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
