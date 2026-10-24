import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import PROPERTY_GETTER_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_property_getter_contract(tmp_path, optimize):
    result = LLVM().assert_matches_python(
        PROPERTY_GETTER_CONTRACT.source, directory=tmp_path, optimize=optimize,
    )
    assert result.native.returncode == 0, PROPERTY_GETTER_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("storage", ["instance", "slots", "dom"])
def test_super_field_reads_and_writes_follow_descriptor_semantics(tmp_path, optimize, storage):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement

class Base(BASE):
    SLOTS
    def __init__(self):
        INITIALIZE
        self.events: list[str] = []
        self.value = 3

class Child(Base):
    def rhs(self, fail: bool) -> int:
        self.events.append("rhs")
        gc_collect()
        if fail:
            raise ValueError("rhs failed")
        return 4
    def read(self) -> str:
        try:
            return str(super().value)
        except AttributeError as error:
            assert "'super' object has no attribute 'value'" in str(error)
            return "missing"
    def write(self, augmented: bool, fail: bool) -> str:
        try:
            if augmented:
                super().value += self.rhs(fail)
            else:
                super().value = self.rhs(fail)
        except AttributeError as error:
            assert "'super' object has no attribute 'value'" in str(error)
            self.events.append("attribute")
        except ValueError:
            self.events.append("value")
        finally:
            self.events.append("finally")
        assert self.value == 3
        result = str(self.events) + ":" + self.read()
        self.value = 9
        return result + ":" + self.read() + ":" + str(self.value)

def main() -> str:
    gc_set_threshold(1)
    result = ""
    for augmented in [False, True]:
        for fail in [False, True]:
            result += Child().write(augmented, fail)
    return result
'''.replace("BASE", "CustomElement" if storage == "dom" else "object").replace(
        "INITIALIZE", "super().__init__()" if storage == "dom" else "pass").replace(
        "SLOTS", "__slots__ = ('events', 'value')" if storage == "slots" else "pass")
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("dom", [False, True], ids=["application", "dom"])
def test_super_property_writes_raise_after_rhs_without_calling_base_setter(tmp_path, optimize, dom):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement

class Base(BASE):
    def __init__(self):
        INITIALIZE
        self.events: list[str] = []
        self.saved = "original"
    @property
    def label(self) -> str:
        self.events.append("get")
        gc_collect()
        return self.saved
    @label.setter
    def label(self, value: str) -> None:
        self.events.append("set")
        self.saved = value

class Child(Base):
    @property
    def label(self) -> str:
        self.events.append("override-get")
        return "override"
    @label.setter
    def label(self, value: str) -> None:
        self.events.append("override-set")
        self.saved = value
    def rhs(self, fail: bool) -> str:
        self.events.append("rhs")
        gc_collect()
        if fail:
            raise ValueError("rhs failed")
        return "new"
    def write(self, augmented: bool, fail: bool) -> str:
        try:
            if augmented:
                super().label += self.rhs(fail)
            else:
                super().label = self.rhs(fail)
        except AttributeError as error:
            self.events.append("attribute")
            assert "'super' object has no attribute 'label'" in str(error)
        except ValueError as error:
            self.events.append(str(error))
        finally:
            self.events.append("finally")
        assert self.saved == "original"
        # Normal writes and subsequent super reads remain usable after failure.
        self.label = "retry"
        return str(self.events) + super().label

def main() -> str:
    gc_set_threshold(1)
    result = ""
    for augmented in [False, True]:
        for fail in [False, True]:
            result += Child().write(augmented, fail)
    return result
'''.replace("BASE", "CustomElement" if dom else "object").replace(
        "INITIALIZE", "super().__init__()" if dom else "pass")
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_uncaught_super_property_write_uses_exception_abi_without_a_handler(tmp_path):
    comparison = LLVM().compare_with_python('''
        class Base:
            @property
            def value(self) -> int:
                return 1
            @value.setter
            def value(self, value: int) -> None:
                raise ValueError("setter must not run")
        class Child(Base):
            def write(self) -> None:
                super().value = 2
        def main() -> int:
            Child().write()
            return 0
    ''', directory=tmp_path, optimize=2, sanitizers=("address", "undefined"))
    # Traceback formats and failure exit codes differ between the runtimes.
    for result in (comparison.python, comparison.native):
        assert result.returncode != 0 and result.stdout == ""
        assert "AttributeError: 'super' object has no attribute 'value'" in result.stderr
        assert "ValueError:" not in result.stderr
    assert "Sanitizer" not in comparison.native.stderr
    assert "runtime error:" not in comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_super_dom_property_setter_does_not_mutate_builtin_storage(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.web.domx import CustomElement
        from pyjs.web.ssr import render_html

        class Item(CustomElement):
            @property
            def textContent(self) -> str:
                return super().textContent
            @textContent.setter
            def textContent(self, value: str | None) -> None:
                super().textContent = value

        def main() -> str:
            item = Item()
            item.append("before<&")
            for value in [None, "new"]:
                try:
                    item.textContent = value
                except AttributeError as error:
                    assert "'super' object has no attribute 'textContent'" in str(error)
                else:
                    raise AssertionError("super write did not raise")
                assert item.textContent == "before<&"
            return render_html(item)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("dom", [False, True], ids=["application", "dom"])
def test_mixed_property_results_box_erased_objects(tmp_path, optimize, dom):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div

class Plain:
    @property
    def textContent(self) -> str:
        return "dom"

class Other:
    @property
    def textContent(self) -> object:
        return "other"

def read(item: RECEIVER | Other) -> object:
    return item.textContent

def main() -> str:
    gc_set_threshold(1)
    items: list[RECEIVER | Other] = [FIRST, Other()]
    values: list[object] = []
    result = ""
    for item in items:
        value = read(item)
        gc_collect()
        values.append(value)
        if isinstance(value, str):
            result += value
        else:
            result += "NOTSTR"
    gc_collect()
    return result + repr(values)
'''.replace("RECEIVER", "Element" if dom else "Plain").replace("FIRST", 'div("dom")' if dom else "Plain()")
    comparison = LLVM().assert_matches_python(
        source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert comparison.native.stdout == "domother['dom', 'other']"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_properties_use_distinct_virtual_slots_and_union_member_layouts(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class First:
            def __init__(self, events: list[str]):
                self.events = events
                self.saved = 1
            @property
            def value(self) -> int:
                self.events.append("first.get")
                gc_collect()
                return self.saved
            @value.setter
            def value(self, value: int) -> None:
                self.events.append("first.set")
                gc_collect()
                if value < 0:
                    raise ValueError("negative")
                self.saved = value

        class Child(First):
            @property
            def value(self) -> int:
                self.events.append("child.get")
                gc_collect()
                return super().value + 10
            @value.setter
            def value(self, value: int) -> None:
                self.events.append("child.set")
                gc_collect()
                self.saved = value + 20

        class Second:
            def __init__(self, events: list[str]):
                self.saved = 2
                self.events = events
            @property
            def value(self) -> int:
                self.events.append("second.get")
                gc_collect()
                if self.saved == 4:
                    raise ValueError("getter failed")
                return self.saved
            @value.setter
            def value(self, value: int) -> None:
                self.events.append("second.set")
                gc_collect()
                self.saved = value

        def owner(value: First | Second, events: list[str]) -> First | Second:
            events.append("owner")
            gc_collect()
            return value

        def replacement(events: list[str], value: int) -> int:
            events.append("rhs")
            if value == -2:
                raise ValueError("rhs failed")
            return value

        def update(value: First | Second, events: list[str]) -> str:
            result: list[int] = []
            for item in [3, -1, -2, 4, 5]:
                try:
                    owner(value, events).value = replacement(events, item)
                except ValueError as error:
                    events.append(str(error))
                try:
                    result.append(owner(value, events).value)
                except ValueError as error:
                    events.append(str(error))
                    result.append(-99)
            owner(value, events).value += replacement(events, 1)
            return str(result) + str(value.value)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values: list[First | Second] = [First(events), Child(events), Second(events)]
            output = ""
            for value in values:
                output += update(value, events)
            return output + str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_property_results_keep_references_and_numeric_representations(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, label: str):
                self.label = label
            def __repr__(self) -> str:
                gc_collect()
                return self.label

        class First:
            @property
            def item(self, suffix: str = "default") -> Box:
                gc_collect()
                return Box("first:" + suffix)
            @property
            def maybe(self) -> None:
                gc_collect()
                return None
            @property
            def number(self) -> int8:
                return int8(130)

        class Second:
            @property
            def item(self) -> str:
                gc_collect()
                return "second" + str(3)
            @property
            def maybe(self) -> Box:
                return Box("present" + str(4))
            @property
            def number(self) -> float32:
                return float32(1.1)

        class Sink:
            def __init__(self):
                self.saved = 0
            @property
            def value(self) -> int:
                return self.saved
            @value.setter
            def value(self, value: int) -> int:
                self.saved = value
                return 99

        def read(value: First | Second) -> str:
            pair = (value.item, value.maybe)
            gc_collect()
            return repr(pair) + repr(value.number)

        def main() -> str:
            gc_set_threshold(1)
            sink = Sink()
            sink.value = 7
            return read(First()) + read(Second()) + str(sink.value)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_property_setters_root_rhs_before_evaluating_receiver(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        class First:
            def __init__(self):
                self.saved = Box(1)
            @property
            def item(self) -> Box:
                gc_collect()
                return self.saved
            @item.setter
            def item(self, value: Box) -> None:
                gc_collect()
                if value.value < 0:
                    raise ValueError("rejected")
                self.saved = value

        class Second:
            def __init__(self):
                self.padding = 2.5
                self.saved = Box(2)
            @property
            def item(self) -> Box:
                return self.saved
            @item.setter
            def item(self, value: Box) -> None:
                gc_collect()
                self.saved = value

        def owner(value: First | Second) -> First | Second:
            gc_collect()
            return value

        def update(value: First | Second) -> str:
            result = ""
            for candidate in [3, -1, 4]:
                old = value.item
                try:
                    owner(value).item = Box(candidate)
                except ValueError as error:
                    result += str(error)
                gc_collect()
                result += str((old.value, value.item.value, old is value.item))
            return result

        def main() -> str:
            gc_set_threshold(1)
            return update(First()) + update(Second())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
