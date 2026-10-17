import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["", ": Box"])
def test_property_assignment_retains_values_and_evaluates_operands_once(optimize, annotation):
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_pin, gc_unpin, gc_set_threshold
        class Box:
            def __init__(self, value: int):
                self.value = value
        class Base:
            def __init__(self):
                self.saved = Box(0)
            @property
            def value(self) -> Box:
                return self.saved
            @value.setter
            def value(self, value: Box) -> None:
                self.saved = value
        class Child(Base):
            @property
            def value(self) -> Box:
                return self.saved
            @value.setter
            def value(self, value: Box) -> None:
                gc_pin(value)
                self.saved = value
        def receiver(target: Base, events: list[int]) -> Base:
            events.append(2)
            gc_collect()
            return target
        def replacement(events: list[int], fail: bool) -> Box:
            events.append(1)
            if fail:
                raise ValueError("before setter")
            return Box(42)
        def store(target: Base, events: list[int], fail: bool) -> None:
            receiver(target, events).value{annotation} = replacement(events, fail)
        def main() -> str:
            gc_set_threshold(1)
            target: Base = Child()
            events: list[int] = []
            try:
                store(target, events, True)
            except ValueError:
                events.append(3)
            store(target, events, False)
            junk = [Box(i) for i in range(30)]
            gc_collect()
            result = repr(events) + str(target.value.value) + str(len(junk))
            gc_unpin(target.value)
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("publish", [False, True], ids=["union-return", "virtual-call-result"])
def test_union_return_and_call_result_dispatch_survive_callee_cleanup(optimize, publish):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_pin, gc_unpin, gc_set_threshold
        class Box:
            def __init__(self, value: int):
                self.value = value
        class First:
            def alias(self, value: Box) -> Box:
                return Box(9)
        class Second:
            def alias(self, value: Box) -> Box:
                return value
            def publish(self) -> None:
                pass
        class Child(Second):
            def publish(self) -> None:
                gc_pin(self)
        def create(owner: First | Second) -> Box:
            return owner.alias(Box(42))
        def identity(value: Second) -> Second:
            return value
        def expose(value: Second) -> None:
            identity(value).publish()
        def main() -> int:
            gc_set_threshold(1)
            child = Child()
            EXPOSE
            first = create(First())
            second = create(child)
            junk = [Box(i) for i in range(30)]
            gc_collect()
            result = first.value + second.value + len(junk)
            UNPIN
            return result
    '''.replace("EXPOSE", "expose(child)" if publish else "pass")
       .replace("UNPIN", "gc_unpin(child)" if publish else "pass"),
       optimize=optimize, sanitizers=("address", "undefined"))
