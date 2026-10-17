import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("disable", ["__hash__ = None", "def __eq__(self, other: object) -> bool: return True"])
@pytest.mark.parametrize("reference", ["Off", "Off()", "value"])
def test_disabled_hash_values_reject_stale_callable_declarations(disable, reference):
    with pytest.raises(LLVMUnsupported, match="disabled __hash__ method values require a nullable callable"):
        transpile_llvm(f'''
            class Root:
                @staticmethod
                def __hash__(value: int = 5) -> int:
                    return value
            class Off(Root):
                {disable}
            def read(value: Root) -> int:
                callback = {reference}.__hash__
                return callback(1)
            def main() -> int:
                return read(Off())
        ''')


@pytest.mark.parametrize("options", ["frozen=True", "unsafe_hash=True"])
@pytest.mark.parametrize("operation", ["return Child.__hash__(4)",
                                      "callback = Child.__hash__; return callback(4)",
                                      "return value.__hash__(4)"])
def test_generated_hash_does_not_fall_back_to_static_ancestor(options, operation):
    with pytest.raises(LLVMUnsupported, match="generated dataclass hashing is not implemented"):
        transpile_llvm(f'''
            from dataclasses import dataclass
            class Root:
                @staticmethod
                def __hash__(value: int = 5) -> int:
                    return value
            @dataclass({options})
            class Child(Root):
                number: int = 0
            def read(value: Root) -> int:
                {operation}
            def main() -> int:
                return read(Child())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_reenabled_static_hash_values_keep_named_class_and_defaults(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int64
        class Root:
            @staticmethod
            def __hash__(value: int = 5) -> int64:
                return int64(value)
        class Off(Root):
            __hash__ = None
        class Child(Off):
            @staticmethod
            def __hash__(value: int = 8) -> int64:
                return int64(100 + value)
        def main() -> str:
            root = Root.__hash__
            child = Child.__hash__
            instance = Child().__hash__
            return str((root(), root(3), child(), child(9), instance()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("disable", ["__hash__ = None", "def __eq__(self, other: object) -> bool: return True"])
def test_class_qualified_disabled_static_hash_keeps_argument_effects(tmp_path, optimize, disable):
    result = LLVM().assert_matches_python(f'''
from pyjs import int64
from pyjs.native import gc_collect, gc_set_threshold

class Root:
    @staticmethod
    def __hash__(value: int = 5, *, extra: int = 6) -> int64:
        return int64(value + extra)

class Off(Root):
    {disable}

class Child(Off):
    @staticmethod
    def __hash__(value: int = 8, *, extra: int = 9) -> int64:
        return int64(value + extra)

def value(events: list[str], label: str) -> int:
    events.append(label)
    gc_collect()
    if label == 'raise':
        raise ValueError('argument')
    return 7

def keywords(events: list[str]) -> dict[str, int]:
    return {{'extra': value(events, 'kw')}}

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    output: list[str] = []
    for mode in range(5):
        try:
            if mode == 0:
                output.append(str(Off.__hash__()))
            elif mode == 1:
                output.append(str(Off.__hash__(value(events, 'pos'), extra=value(events, 'kw'))))
            elif mode == 2:
                output.append(str(Off.__hash__(*(value(events, 'pos'),), **keywords(events))))
            elif mode == 3:
                Off.__hash__(**keywords(events), **keywords(events))
            else:
                Off.__hash__(value(events, 'raise'))
        except TypeError as error:
            output.append('duplicate' if 'multiple values' in str(error) else str(error))
        except ValueError as error:
            output.append(str(error))
    output.append(str(Root.__hash__()))
    output.append(str(Child.__hash__()))
    return '|'.join(output) + str(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("receiver", ["Root", "Root | Other"])
def test_disabled_static_hash_preserves_lookup_operands_and_defaults(tmp_path, optimize, receiver):
    result = LLVM().assert_matches_python(f'''
        from pyjs import int64
        from pyjs.native import gc_collect, gc_set_threshold
        class Root:
            @staticmethod
            def __hash__(value: int = 5, *, extra: int = 6) -> int64:
                return int64(value + extra)
        class Off(Root):
            __hash__ = None
        class EqOff(Root):
            def __eq__(self, other: object) -> bool:
                return True
        class Child(Off):
            @staticmethod
            def __hash__(value: int = 8, *, extra: int = 9) -> int64:
                return int64(value + extra)
            def parent(self) -> int64:
                parent = super()
                return parent.__hash__()
        class Enabled(Child):
            def parent(self) -> int64:
                return super().__hash__()
        class Other:
            @staticmethod
            def __hash__(value: int = 2, *, extra: int = 3) -> int64:
                return int64(value + extra)
        def value(events: list[str], label: str) -> int:
            events.append(label)
            gc_collect()
            if label == 'raise':
                raise ValueError('argument')
            return 7
        def keywords(events: list[str]) -> dict[str, int]:
            return {{'extra': value(events, 'kw')}}
        def read(receiver: {receiver}, events: list[str], mode: int) -> str:
            try:
                if mode == 0:
                    return str(receiver.__hash__())
                if mode == 1:
                    return str(receiver.__hash__(value(events, 'pos'), extra=value(events, 'kw')))
                if mode == 2:
                    return str(receiver.__hash__(*(value(events, 'pos'),), **keywords(events)))
                if mode == 4:
                    return str(receiver.__hash__(value(events, 'raise')))
                receiver.__hash__(**keywords(events), **keywords(events))
                return 'unexpected'
            except TypeError as error:
                return 'duplicate' if 'multiple values' in str(error) else str(error)
            except ValueError as error:
                return str(error)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            output: list[str] = []
            for mode in range(5):
                output.append(read(Off(), events, mode))
                output.append(read(EqOff(), events, mode))
                output.append(read(Root(), events, mode))
                output.append(read(Child(), events, mode))
                {"output.append(read(Other(), events, mode))" if "Other" in receiver else "pass"}
            try:
                Child().parent()
            except TypeError as error:
                output.append(str(error))
            output.append(str(Enabled().parent()))
            output.append(str(Root.__hash__()))
            return '|'.join(output) + str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("disable", ["__hash__ = None", "def __eq__(self, other: object) -> bool: return True"])
@pytest.mark.parametrize("receiver", ["Root", "Root | Other"])
def test_disabled_authored_hash_stays_disabled_through_calls_and_super(tmp_path, optimize, disable, receiver):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Root:
            def __hash__(self) -> int:
                return 5
        class Parent(Root):
            {disable}
        class Child(Parent):
            def __hash__(self) -> int:
                return -1
            def base(self) -> int:
                parent = super()
                return parent.__hash__()
        class Other:
            def __hash__(self) -> int:
                return 9
        def direct(value: {receiver}) -> int:
            return value.__hash__()
        def main() -> str:
            gc_set_threshold(1)
            output: list[str] = []
            for _ in range(2):
                try:
                    Parent().__hash__()
                except TypeError as error:
                    output.append(str(error))
                try:
                    direct(Parent())
                except TypeError as error:
                    output.append(str(error))
                try:
                    Child().base()
                except TypeError as error:
                    output.append(str(error))
                gc_collect()
                output.append(str((direct(Root()), direct(Child()), hash(Child()))))
                {"output.append(str(direct(Other())))" if "Other" in receiver else "pass"}
            return '|'.join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expanded", [False, True])
@pytest.mark.parametrize("receiver_type", ["Root", "Root | Other"])
def test_disabled_hash_evaluates_operands_once_before_error(tmp_path, optimize, expanded, receiver_type):
    call = ("receiver.__hash__(*arguments(events), **keywords(events))" if expanded else
            "receiver.__hash__(value(events, 'pos'), extra=value(events, 'kw'))")
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Root:
            def __hash__(self, value: int = 5, *, extra: int = 6) -> int:
                return value + extra
        class Disabled(Root):
            __hash__ = None
        class Other:
            def __hash__(self, value: int = 8, *, extra: int = 9) -> int:
                return value + extra
        def value(events: list[str], label: str) -> int:
            events.append(label)
            gc_collect()
            return 7
        def arguments(events: list[str]) -> tuple[int]:
            return (value(events, 'pos'),)
        def keywords(events: list[str]) -> dict[str, int]:
            return {{'extra': value(events, 'kw')}}
        def attempt(receiver: {receiver_type}, events: list[str]) -> int:
            try:
                return {call}
            except TypeError as error:
                events.append(str(error))
                return -1
        def duplicate(receiver: {receiver_type}, events: list[str]) -> bool:
            try:
                receiver.__hash__(**keywords(events), **keywords(events))
            except TypeError as error:
                return 'multiple values' in str(error)
            return False
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            result = [attempt(Disabled(), events), attempt(Root(), events)]
            {"result.append(attempt(Other(), events))" if "Other" in receiver_type else "pass"}
            duplicated = duplicate(Disabled(), events)
            return str((result, duplicated, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind,value", [("bool", "True"), ("int64", "int64(-1)")])
@pytest.mark.parametrize("receiver", ["Root", "Root | Other"])
def test_disabled_hash_guard_preserves_authored_result_storage(tmp_path, optimize, kind, value, receiver):
    result = LLVM().assert_matches_python(f'''
        from pyjs import int64
        class Root:
            def __hash__(self) -> {kind}:
                return {value}
        class Disabled(Root):
            __hash__ = None
        class Other:
            def __hash__(self) -> {kind}:
                return {value}
        def direct(value: {receiver}) -> {kind}:
            return value.__hash__()
        def main() -> str:
            output = str(direct(Root()))
            {"output += '|' + str(direct(Other()))" if "Other" in receiver else "pass"}
            try:
                direct(Disabled())
            except TypeError as error:
                output += '|' + str(error)
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
