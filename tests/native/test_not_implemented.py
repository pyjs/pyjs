import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.comparison_fixtures import COMPARISON_PAIRS, declining_pair


def assert_parity(source, *, directory, optimize):
    result = LLVM().assert_matches_python(
        source, directory=directory, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.stderr == ""


@pytest.mark.parametrize("operator, method", [
    ("+", "add"), ("-", "sub"), ("*", "mul"),
    ("/", "truediv"), ("//", "floordiv"), ("%", "mod"), ("**", "pow"),
    ("<<", "lshift"), (">>", "rshift"), ("&", "and"), ("|", "or"), ("^", "xor"),
])
@pytest.mark.parametrize("annotation", ["", " -> NotImplementedType", " -> int | NotImplementedType", " -> object"])
def test_arithmetic_decline_is_diagnosed_before_emission(operator, method, annotation):
    with pytest.raises(LLVMUnsupported, match="arithmetic operators do not yet support NotImplemented results") as caught:
        transpile_llvm(f'''from types import NotImplementedType
class Left:
    def __{method}__(self, other: object){annotation}:
        return NotImplemented
class Right:
    def __r{method}__(self, other: object) -> int:
        return 7
def main() -> str:
    return str(Left() {operator} Right())
''')
    assert caught.value.node.lineno is not None


@pytest.mark.parametrize("expression", ["Left() + Right()", "op.add(Left(), Right())"])
@pytest.mark.parametrize("reflected", [False, True])
def test_arithmetic_decline_boundary_includes_reflected_and_operator_wrappers(expression, reflected):
    left = "pass" if reflected else "def __add__(self, other: object): return NotImplemented"
    right = "def __radd__(self, other: object): return NotImplemented" if reflected else "pass"
    with pytest.raises(LLVMUnsupported, match="arithmetic operators do not yet support NotImplemented results"):
        transpile_llvm(f'''import operator as op
class Left:
    {left}
class Right:
    {right}
def main() -> str:
    return str({expression})
''')


@pytest.mark.parametrize("annotation", ["", " -> NotImplementedType", " -> tuple[int, int] | NotImplementedType", " -> object"])
@pytest.mark.parametrize("expression, method", [
    ("divmod(Item(), 3)", "__divmod__"),
    ("divmod(3, Item())", "__rdivmod__"),
    ("divmod(Item(), Other())", "__divmod__"),
])
def test_divmod_builtin_keeps_its_arithmetic_boundary_after_dunder_lowering(annotation, expression, method):
    with pytest.raises(LLVMUnsupported, match="arithmetic operators do not yet support NotImplemented results") as caught:
        transpile_llvm(f'''from types import NotImplementedType
class Item:
    def {method}(self, other: object){annotation}:
        return NotImplemented
class Other:
    def __rdivmod__(self, other: object) -> tuple[int, int]:
        return (7, 8)
def main() -> str:
    return str({expression})
''')
    assert caught.value.node.lineno is not None


def test_runtime_reflected_override_cannot_hide_a_declining_arithmetic_result():
    with pytest.raises(LLVMUnsupported, match="arithmetic operators do not yet support NotImplemented results"):
        transpile_llvm('''
from types import NotImplementedType
class Base:
    def __add__(self, other: object) -> object:
        return 1
class Child(Base):
    def __radd__(self, other: object) -> NotImplementedType:
        return NotImplemented
def operate(left: Base, right: Base) -> object:
    return left + right
def main() -> str:
    return str(operate(Base(), Child()))
''')


def test_augmented_arithmetic_decline_is_diagnosed_before_writeback():
    with pytest.raises(LLVMUnsupported, match="arithmetic operators do not yet support NotImplemented results"):
        transpile_llvm('''
from types import NotImplementedType
class Item:
    def __iadd__(self, other: object) -> NotImplementedType:
        return NotImplemented
def main() -> str:
    item = Item()
    item += 1
    return str(item)
''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", [
    "value + value", "value + 1", "op.add(value, value)", "augmented",
    "divmod(value, 3)", "divmod(3, value)",
])
def test_erased_dynamic_arithmetic_decline_is_an_explicit_runtime_boundary(tmp_path, optimize, operation):
    statement = "value += 1\n            result = value" if operation == "augmented" else f"result = {operation}"
    result = LLVM().run_source(f'''
import operator as op
from pyjs.native import gc_collect
class Item:
    def __init__(self, result: object):
        self.result = result
    def __add__(self, other: object) -> object:
        gc_collect()
        return self.result
    def __iadd__(self, other: object) -> object:
        gc_collect()
        return self.result
    def __divmod__(self, other: object) -> object:
        gc_collect()
        return self.result
    def __rdivmod__(self, other: object) -> object:
        gc_collect()
        return self.result
def main() -> str:
    results: list[str] = []
    for returned in [7, NotImplemented, "ok"]:
        original = Item(returned)
        value: object = original
        assert isinstance(value, Item)
        try:
            {statement}
            results.append(str(result))
        except TypeError as error:
            assert str(error) == "LLVM arithmetic operators do not yet support NotImplemented results"
            results.append("unsupported decline")
            assert original.__add__(original) is NotImplemented
        gc_collect()
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.stdout == "['7', 'unsupported decline', 'ok']"
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_arithmetic_dunder_calls_preserve_declined_results(tmp_path, optimize):
    assert_parity('''
from types import NotImplementedType
class Item:
    def __add__(self, other: object) -> int | NotImplementedType:
        return NotImplemented
    def __radd__(self, other: object) -> NotImplementedType:
        return NotImplemented
    def __iadd__(self, other: object) -> NotImplementedType:
        return NotImplemented
    def __divmod__(self, other: object) -> NotImplementedType:
        return NotImplemented
    def __rdivmod__(self, other: object) -> NotImplementedType:
        return NotImplemented
def divmod(left: object, right: object) -> NotImplementedType:
    return NotImplemented
def main() -> str:
    item = Item()
    return str((item.__add__(item) is NotImplemented,
                item.__radd__(item) is NotImplemented,
                item.__iadd__(item) is NotImplemented,
                item.__divmod__(item) is NotImplemented,
                item.__rdivmod__(item) is NotImplemented,
                divmod(item, item) is NotImplemented))
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operator, forward, reflected", COMPARISON_PAIRS)
@pytest.mark.parametrize("result", ["NotImplementedType", "bool | NotImplementedType"])
def test_isolated_comparison_reaches_forward_and_reflected_bodies(tmp_path, optimize, operator, forward, reflected, result):
    assert_parity(declining_pair(operator, forward, reflected, result), directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operator", ["==", "!="])
def test_single_nonvirtual_class_comparison_needs_no_incidental_dunder_call(tmp_path, optimize, operator):
    assert_parity(f'''
from types import NotImplementedType
class Item:
    def __eq__(self, other: object) -> bool | NotImplementedType:
        return NotImplemented
def main() -> str:
    item = Item()
    return str((item {operator} item, item {operator} Item()))
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_ordering_syntax_negotiates_without_exposing_the_sentinel(tmp_path, optimize):
    assert_parity('''
        from types import NotImplementedType
        from pyjs.native import gc_collect, gc_set_threshold

        class Rank:
            def __init__(self, name: str, decline: bool, events: list[str]):
                self.name = name
                self.decline = decline
                self.events = events

            def result(self, method: str) -> bool | NotImplementedType:
                self.events.append(self.name + method)
                gc_collect()
                if self.decline:
                    return NotImplemented
                return False

            def __lt__(self, other: Rank) -> bool | NotImplementedType:
                return self.result("lt")

            def __le__(self, other: Rank) -> bool | NotImplementedType:
                return self.result("le")

            def __gt__(self, other: Rank) -> bool | NotImplementedType:
                return self.result("gt")

            def __ge__(self, other: Rank) -> bool | NotImplementedType:
                return self.result("ge")

        class Child(Rank):
            def __gt__(self, other: Rank) -> bool:
                self.events.append(self.name + "child.gt")
                gc_collect()
                return True

        def compare(left: Rank, right: Rank) -> str:
            values: list[bool] = [left < right, left <= right, left > right, left >= right]
            return str(values)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            left = Rank("left", True, events)
            right = Rank("right", False, events)
            child = Child("child", False, events)
            results = [compare(left, right), compare(right, left), compare(left, child)]
            right.decline = True
            try:
                compare(left, right)
            except TypeError as error:
                results.append(str(error))
            return str((results, events, left.__lt__(right) is NotImplemented))
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_not_implemented_comparisons_negotiate_once_in_python_order(tmp_path, optimize):
    assert_parity('''
        from types import NotImplementedType
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, name: str, mode: int, events: list[str]):
                self.name = name
                self.mode = mode
                self.events = events

            def __eq__(self, other: object) -> bool | NotImplementedType:
                self.events.append(self.name + ".eq")
                gc_collect()
                if self.mode == 2:
                    return NotImplemented
                return self.mode == 1

        class Child(Base):
            def __eq__(self, other: object) -> bool | NotImplementedType:
                self.events.append(self.name + ".child.eq")
                gc_collect()
                if self.mode == 2:
                    return NotImplemented
                return self.mode == 1

        class Explicit(Base):
            def __ne__(self, other: object) -> bool | NotImplementedType:
                self.events.append(self.name + ".ne")
                gc_collect()
                if self.mode == 2:
                    return NotImplemented
                return self.mode == 1

        class Declines:
            def __eq__(self, other: object) -> NotImplementedType:
                return NotImplemented

        def typed(left: Base, right: Base) -> tuple[bool, bool]:
            return left == right, left != right

        def erased(left: object, right: object) -> tuple[bool, bool]:
            return left == right, left != right

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values: list[Base] = []
            for mode in range(3):
                values.append(Base("base" + str(mode), mode, events))
                values.append(Child("child" + str(mode), mode, events))
                values.append(Explicit("explicit" + str(mode), mode, events))
            results: list[tuple[bool, bool]] = []
            for left in values:
                for right in values:
                    results.append(typed(left, right))
                    results.append(erased(left, right))
                    results.append(([left] == [right], [left] != [right]))
            declined = Declines()
            results.append(erased(declined, declined))
            results.append(erased(declined, Declines()))
            results.append(erased(declined, NotImplemented))
            return str((results, events))
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("annotation, result", [("bool", "True"), ("NotImplementedType", "NotImplemented")])
@pytest.mark.parametrize("optimize", [0, 2])
def test_declining_virtual_callbacks_adapt_covariant_return_storage(tmp_path, annotation, result, optimize):
    assert_parity(f'''
            from types import NotImplementedType

            class Base:
                def __eq__(self, other: object) -> bool | NotImplementedType:
                    return NotImplemented

            class Child(Base):
                def __eq__(self, other: object) -> {annotation}:
                    return {result}

            def compare(left: Base, right: Base) -> str:
                callback = right.__eq__
                return str((left == right, left != right, callback(left) is NotImplemented))

            def main() -> str:
                return compare(Base(), Child())
        ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_not_implemented_retains_singleton_identity_in_union_returns(tmp_path, optimize):
    assert_parity('''
        from types import NotImplementedType

        def choose(flag: bool) -> bool | NotImplementedType:
            return True if flag else NotImplemented

        def main() -> str:
            first = choose(False)
            second = choose(True)
            return str((first is NotImplemented, second is NotImplemented))
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_not_implemented_formats_and_survives_erasure_and_collection(tmp_path, optimize):
    assert_parity('''
        from types import NotImplementedType
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [NotImplemented, None, True, 1, "text"]
            typed: list[NotImplementedType] = [NotImplemented]
            gc_collect()
            results: list[bool] = []
            for value in values:
                results.append(value is NotImplemented)
                results.append(value == NotImplemented)
                results.append(value != NotImplemented)
            results.append(NotImplemented == NotImplemented)
            results.append(NotImplemented != 1)
            return str((values, typed, results, repr(NotImplemented)))
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_not_implemented_truth_errors_are_catchable_after_erasure(tmp_path, optimize):
    assert_parity('''
        from types import NotImplementedType
        from pyjs.native import gc_collect

        def typed(value: NotImplementedType) -> bool:
            return bool(value)

        def erased(value: object) -> bool:
            return bool(value)

        def union(value: bool | NotImplementedType) -> bool:
            return bool(value)

        def main() -> str:
            messages: list[str] = []
            for mode in range(4):
                try:
                    if mode == 0:
                        typed(NotImplemented)
                    elif mode == 1:
                        erased(NotImplemented)
                    elif mode == 2:
                        union(NotImplemented)
                    else:
                        any([NotImplemented])
                except TypeError as error:
                    messages.append(str(error))
                gc_collect()
            return str((messages, union(True), erased(False)))
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_declining_comparisons_unwind_after_reflected_errors_and_retry(tmp_path, optimize):
    assert_parity('''
        from types import NotImplementedType
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, mode: int, events: list[int]):
                self.mode = mode
                self.events = events

            def __eq__(self, other: object) -> bool | NotImplementedType:
                self.events.append(self.mode)
                gc_collect()
                if self.mode == 0:
                    return NotImplemented
                if self.mode == 1:
                    raise ValueError("comparison failed")
                return True

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            left = Item(0, events)
            right = Item(1, events)
            values: list[object] = [left]
            results: list[str] = []
            for attempt in range(2):
                for operation in range(3):
                    try:
                        if operation == 0:
                            results.append(str(left == right))
                        elif operation == 1:
                            results.append(str(values.count(right)))
                        else:
                            results.append(str([left] != [right]))
                    except ValueError as error:
                        results.append(str(error))
                    gc_collect()
                right.mode = 2
            return str((results, events))
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_not_implemented_typed_collection_comparisons(tmp_path, optimize):
    assert_parity('''
        from types import NotImplementedType

        def main() -> str:
            values: list[NotImplementedType] = [NotImplemented]
            copied: list[NotImplementedType] = [NotImplemented]
            results = (values == copied, NotImplemented in values,
                       values.count(NotImplemented), values.index(NotImplemented))
            values.remove(NotImplemented)
            return str((results, values))
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_declining_typed_container_callbacks_retain_arguments(tmp_path, optimize):
    assert_parity('''
        from types import NotImplementedType
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        class Payload:
            def __init__(self, value: int):
                self.value = value

        class Owner:
            def __init__(self):
                self.saved: object = None

            def __eq__(self, other: object) -> NotImplementedType:
                self.saved = other
                gc_collect()
                return NotImplemented

        def retain(owner: Owner, reflected: bool) -> bool:
            value = Payload(42)
            if reflected:
                return [[value]] == [[owner]]
            return [[owner]] == [[value]]

        def main() -> str:
            gc_set_threshold(1)
            owner = Owner()
            results: list[int] = []
            for reflected in [False, True]:
                results.append(int(retain(owner, reflected)))
                gc_collect()
                extra = Payload(-1)
                results.append(cast(Payload, owner.saved).value)
                results.append(extra.value)
            return str(results)
    ''', directory=tmp_path, optimize=optimize)
