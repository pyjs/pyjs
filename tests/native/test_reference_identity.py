import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_reference_ids_preserve_aliases_and_distinguish_live_objects(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int):
                self.value = value
        def erased(value: object) -> object:
            gc_collect()
            return value
        def optional(value: list[Box] | None) -> int:
            return id(value)
        def main() -> str:
            gc_set_threshold(1)
            left = Box(1)
            alias = left
            right = Box(1)
            values = [left]
            boxed = erased(values)
            saved = id(boxed)
            gc_collect()
            assert id(left) == id(alias) and id(left) != id(right)
            assert id(values) == id(boxed) == saved
            assert optional(values) == id(values) and optional(None) == id(None)
            assert boxed is values
            absent: list[Box] | None = None
            assert id(absent) == id(None)
            absent = values
            assert id(absent) == id(values)
            return str([left.value, right.value, len(values)])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_ids_ignore_convention_views_not_allocated_identity(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from functools import partial
        from pyjs.native import gc_collect, gc_set_threshold
        def answer(value: int = 42) -> int:
            gc_collect()
            return value
        def other_answer(value: int = 42) -> int:
            gc_collect()
            return value
        def captured(value: int) -> Callable[[], int]:
            return lambda: value
        class Box:
            def read(self, value: int = 1) -> int:
                return value
        def main() -> str:
            gc_set_threshold(1)
            view: Callable[[], int | None] = answer
            broad: Callable[[], object] = view
            bound = partial(answer, 3)
            other = partial(answer, 3)
            first = captured(4)
            second = captured(4)
            box = Box()
            method = box.read
            again = box.read
            gc_collect()
            assert id(answer) == id(view) == id(broad)
            assert answer == view and broad == answer and not (view != broad)
            assert answer != other_answer and id(answer) != id(other_answer)
            assert answer != None and None != answer
            assert not (answer == None) and not (None == answer)
            assert answer is broad and broad is view
            assert id(bound) != id(other) and bound is not other
            assert id(first) != id(second) and first is not second
            assert id(method) != id(again) and method is not again
            return str([view(), broad(), bound(), first(), method()])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_and_application_iterator_views_keep_original_ids(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self):
                self.current = 0
            def __iter__(self) -> "Cursor":
                return self
            def __next__(self) -> int:
                self.current += 1
                if self.current > 2:
                    raise StopIteration()
                return self.current
        def view(value: Iterable[int]) -> Iterable[int]:
            gc_collect()
            return value
        def cursor(value: Iterator[int]) -> Iterator[int]:
            gc_collect()
            return value
        def main() -> str:
            gc_set_threshold(1)
            values = [1, 2]
            items = view(values)
            assert id(items) == id(values) and items is values
            source = Cursor()
            first = cursor(source)
            second = cursor(source)
            assert id(first) == id(second) == id(source)
            assert first is second and second is source
            assert id(view(first)) == id(source)
            return str([next(first), next(second), sum(items)])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("expression", ["3", "1.5", "True"])
def test_unboxed_values_do_not_claim_python_object_ids(expression):
    with pytest.raises(LLVMUnsupported, match="only reference values"):
        transpile_llvm(f"def main() -> int:\n    return id({expression})\n")


@pytest.mark.parametrize("declaration,name", [("import math", "math"), ("import math as module", "module")])
def test_module_ids_have_a_located_diagnostic(declaration, name):
    with pytest.raises(LLVMUnsupported, match="id does not support module values at line"):
        transpile_llvm(f"{declaration}\ndef main() -> int:\n    return id({name})\n")


def test_tagged_reference_ids_suggest_narrowing():
    with pytest.raises(LLVMUnsupported, match="tagged multi-member unions; narrow the value first"):
        transpile_llvm('''
            class A:
                pass
            class B:
                pass
            def identify(value: A | B) -> int:
                return id(value)
            def main() -> int:
                return identify(A())
        ''')


@pytest.mark.parametrize("base,value", [("IntEnum", "1"), ("StrEnum", "'name'")])
def test_scalar_enum_ids_do_not_expose_their_underlying_payload(base, value):
    with pytest.raises(LLVMUnsupported, match="scalar enums"):
        transpile_llvm(f'''
            from enum import {base}
            class Label({base}):
                VALUE = {value}
            def main() -> int:
                return id(Label.VALUE)
        ''')


@pytest.mark.parametrize("dunder", ["__eq__", "__ne__"])
@pytest.mark.parametrize("other", ["callback", "None"])
def test_explicit_callable_comparison_dunders_do_not_erase_notimplemented(dunder, other):
    with pytest.raises(LLVMUnsupported, match="explicit callable comparison dunders may return NotImplemented"):
        transpile_llvm(f'''
            from collections.abc import Callable
            def source(value: int) -> int:
                return value
            def compare(callback: Callable[[int], int]) -> str:
                return str(callback.{dunder}({other}))
            def main() -> str:
                return compare(source)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("default", ["", " = 10"], ids=["fixed", "optional"])
def test_callable_equality_selects_the_actual_method_and_preserves_capture_identity(tmp_path, optimize, default):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from functools import partial
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def read(self, value: int{default}) -> int:
                return value + 1
            def inherited(self, value: int{default}) -> int:
                return value + 3
            def __eq__(self, other: object) -> bool:
                raise ValueError("receiver equality must not run")
        class Child(Base):
            def read(self, value: int{default}) -> int:
                return value + 2
            def parent(self) -> Callable[[int], int]:
                return super().read
        class Other:
            def read(self, value: int{default}) -> int:
                return value + 5
        def bind(value: Base | Other) -> Callable[[int], int]:
            return value.read
        def optional(left: Callable[[int], int] | None,
                     right: Callable[[int], int] | None) -> bool:
            gc_collect()
            return left == right and not (left != right)
        def widen(callback: Callable[[int], object]) -> Callable[[int], object]:
            gc_collect()
            return callback
        def capture(value: int) -> Callable[[int], int]:
            return lambda arg: arg + value
        def main() -> str:
            gc_set_threshold(1)
            child = Child()
            base: Base = child
            other = Child()
            first = base.read
            second = child.read
            broad = widen(first)
            gc_collect()
            assert first == second and second == broad and broad == first
            assert not (first != second) and first is not second
            assert first != other.read and first != child.parent()
            assert base.inherited == child.inherited
            assert bind(child) == first and bind(other) != first
            alternate = Other()
            assert bind(alternate) == alternate.read and bind(alternate) != first
            assert optional(first, second) and optional(None, None)
            assert not optional(first, None) and not optional(None, first)
            functions = [first, second]
            assert functions == [second, first] and first in functions
            assert functions.count(second) == 2
            one = capture(3)
            two = capture(3)
            assert one == one and one != two
            left = partial(first, 4)
            right = partial(first, 4)
            assert left == left and left != right
            return str([first(1), second(2), left(), one(4)])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dom_ids_canonicalize_concrete_element_and_erased_views(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, div
        class Panel(CustomElement):
            def __init__(self):
                super().__init__()
        def element(value: Element | None) -> int:
            gc_collect()
            return id(value)
        def erased(value: object) -> int:
            gc_collect()
            return id(value)
        def main() -> str:
            gc_set_threshold(1)
            first = Panel()
            second = Panel()
            plain = div()
            assert id(first) == element(first) == erased(first)
            assert id(first) != id(second) and id(first) != id(plain)
            assert id(plain) == element(plain) == erased(plain)
            assert element(None) == erased(None) == id(None)
            return "ok"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("classes,sites", [(2, 1), (16, 20)])
def test_virtual_binding_dispatch_is_shared_across_extraction_sites(classes, sites):
    declarations = "\n".join(f'''
class Child{i}(Base):
    def read(self, value: int) -> int:
        return value + {i}
''' for i in range(classes))
    choices = "\n".join(f"    if value == {i}:\n        return Child{i}()" for i in range(classes))
    bindings = "\n".join(f"    callbacks.append(pick({i % classes}).read)" for i in range(sites))
    ir = transpile_llvm(f'''
from collections.abc import Callable
class Base:
    def read(self, value: int) -> int:
        return value
{declarations}
def pick(value: int) -> Base:
{choices}
    return Child0()
def main() -> int:
    callbacks: list[Callable[[int], int]] = []
{bindings}
    return sum(callback(1) for callback in callbacks)
''')
    # Assert the structural bound, not wall-clock timings or unrelated runtime
    # text: one shared selection helper, one ordinary call per extraction site.
    assert ir.count("define ptr @pyjs.callable.bind.") == 1
    body = ir.split("define i64 @fn.pyjs_main(", 1)[1].split("\n}", 1)[0]
    assert body.count("call ptr @pyjs.callable.bind.0(") == sites
    assert ".read.callback" not in body


@pytest.mark.parametrize("optimize", [0, 2])
def test_failed_outlined_binding_keeps_previous_identity_and_can_retry(tmp_path, optimize):
    ir = transpile_llvm('''
        from collections.abc import Callable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        class Base:
            def read(self, value: int) -> int:
                return value + 1
        class Child(Base):
            def read(self, value: int) -> int:
                return value + 2
        def sentinel(value: int) -> object:
            return "prior"
        def main() -> int:
            child = Child()
            source: Base = child
            for allocation in (1, 2):
                callback: Callable[[int], object] = sentinel
                caught = False
                arm(allocation)
                try:
                    callback = source.read
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                assert caught and callback == sentinel and id(callback) == id(sentinel)
                assert callback(5) == "prior"
                callback = source.read
                gc_collect()
                assert callback == child.read and callback(5) == 7
            return 0
    ''')
    # Allocation denial uses the unsanitized harness; sanitizer execution has
    # separate coverage and must not inherit this harness's address-space cap.
    run_allocation_case(ir, tmp_path, managed=True, optimize=optimize)
