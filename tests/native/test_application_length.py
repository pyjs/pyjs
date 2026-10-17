import pytest

from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_length_dispatch_errors_and_recovery(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, events: list[int], size: int):
                self.events = events
                self.size = size

        class Sized(Base):
            def __len__(self) -> int:
                self.events.append(self.size)
                gc_collect()
                if self.size == 7:
                    raise RuntimeError("size unavailable")
                return self.size

        class Inherited(Sized):
            def __bool__(self) -> bool:
                raise AssertionError("len must not call bool")

        class Doubled(Sized):
            def __len__(self) -> int:
                self.events.append(10)
                gc_collect()
                return self.size * 2

        class Disabled(Sized):
            __len__ = None

        class StillDisabled(Disabled):
            pass

        def measure(value: Base) -> int:
            return len(value)

        def create(events: list[int], size: int) -> Base:
            events.append(20)
            gc_collect()
            if size == 8:
                raise LookupError("creation failed")
            return Doubled(events, size)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            results: list[int] = []
            values: list[Base] = [Base(events, 1), Sized(events, 0), Sized(events, -1),
                                  Inherited(events, 3), Doubled(events, 4), Sized(events, 7),
                                  Disabled(events, 9), StillDisabled(events, 10)]
            for value in values:
                try:
                    results.append(measure(value))
                except TypeError:
                    results.append(-10)
                except ValueError:
                    results.append(-20)
                except RuntimeError:
                    results.append(-30)
                gc_collect()
            # Fresh temporaries are rooted through the callback, and evaluating
            # the receiver is distinct from executing its length protocol.
            results.append(len(create(events, 5)))
            try:
                results.append(len(create(events, 8)))
            except LookupError:
                results.append(-40)
            recovered = Sized(events, -1)
            try:
                measure(recovered)
            except ValueError:
                recovered.size = 6
            results.append(measure(recovered))
            return repr((results, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_length_defaults_bool_and_builtin_controls(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Flag:
            def __len__(self) -> bool:
                return True
        class Defaults:
            def __len__(self, extra: int = 2, *, scale: int = 3) -> int:
                return extra * scale
        def main() -> str:
            mapping = {"one": 1, "two": 2}
            sizes = [len(Flag()), len(Defaults()), len("aé😀"), len(b"abc"),
                     len([1, 2]), len((1, "x")), len({1, 2}), len(frozenset([1])),
                     len(range(1, 9, 3)), len(mapping), len(mapping.keys()),
                     len(mapping.values()), len(mapping.items())]
            return repr((sizes, bool(Flag()), bool(Defaults())))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_missing_and_disabled_length_error_text(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Base:
            pass
        class Other(Base):
            pass
        class Sized(Base):
            def __len__(self) -> int:
                return 1
        class Disabled(Sized):
            __len__ = None
        class StillDisabled(Disabled):
            pass
        def measure(value: Base) -> str:
            try:
                return repr(len(value))
            except TypeError as error:
                return str(error)
        def main() -> str:
            return repr([measure(Base()), measure(Other()), measure(Sized()),
                         measure(Disabled()), measure(StillDisabled())])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_length_and_truth_prepare_runtime_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Sized[T]:
            def __init__(self, value: T):
                self.value = value
            def __len__(self) -> T:
                gc_collect()
                return self.value
        class Child(Sized[int]):
            def __len__(self) -> int:
                return super().__len__() + 2
        # Accept both concrete specializations without aliasing their fields.
        def measure(value: Sized[int] | Sized[bool]) -> int:
            return len(value)
        def main() -> str:
            gc_set_threshold(1)
            return repr(([len(Sized[int](3)), len(Sized[bool](True)),
                          measure(Sized[int](4)), measure(Child(5)), measure(Sized[bool](False))],
                         [bool(Sized[int](0)), bool(Sized[bool](True)), bool(Child(0))]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_optional_length_without_a_reached_concrete_instance(tmp_path):
    result = LLVM().assert_matches_python('''
        class Sized:
            def __len__(self) -> int:
                return 2
        def measure(value: Sized | None) -> int:
            try:
                return len(value)
            except TypeError:
                return 42
        def main() -> int:
            return measure(None)
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.returncode == 42
    assert result.native.stderr == ""


def test_host_record_length_without_a_python_constructor_call(tmp_path):
    library = LLVM().compile_library('''
        class Sized:
            def __init__(self, text: str):
                self.text = text
            def __len__(self) -> int:
                return len(self.text)
        def render(values: list[Sized]) -> str:
            return str(len(values[0]))
    ''', tmp_path, entry_point="render")
    try:
        assert library.render([{"text": "aé😀"}]) == "3"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("item_type, local_type, expression, expected", [
    ("int", "bool", "repr([bool(values[0]), bool(local), values[0].item])", "[True, True, 3]"),
    ("int", "bool", "repr([hash(values[0]) == hash(values[0]), hash(local) == hash(local)])", "[True, True]"),
    ("float", "int", "repr([describe(values[0]), describe(None), local.item])", "['full', 'empty', 3]"),
])
def test_single_group_protocol_preserves_generic_host_record_abi(
    tmp_path, optimize, item_type, local_type, expression, expected,
):
    # Multiple compatible generic classes do not imply runtime dispatch:
    # all these classes share default truth and identity hashing. Unneeded
    # headers would unnecessarily require nominal rather than structural input.
    library = LLVM().compile_library(f'''
        class Box[T]:
            def __init__(self, item: T):
                self.item = item
        def describe(box: Box[{item_type}] | None) -> str:
            return "full" if box else "empty"
        def render(values: list[Box[{item_type}]]) -> str:
            local = Box[{local_type}]({"True" if local_type == "bool" else "3"})
            return {expression}
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render([{"item": 1.5 if item_type == "float" else 3}]) == expected
    finally:
        library.close()


@pytest.mark.parametrize("operation, method, result_type, body, expected", [
    ("len", "__len__", "int", "int(self.item)", "(4, 1)"),
    ("bool", "__bool__", "bool", "bool(self.item)", "(True, True)"),
    ("hash", "__hash__", "int", "int(self.item)", "(4, 1)"),
    ("bin", "__index__", "int", "int(self.item)", "('0b100', '0b1')"),
])
def test_dispatched_generic_protocol_promotes_exact_host_identity(
    tmp_path, operation, method, result_type, body, expected,
):
    # Each specialization has its own method, unlike default truth/hash.
    # Input shape fixes its specialization; structural substitutes must not
    # acquire a callable native identity just by having the same field names.
    library = LLVM().compile_library(f'''
        class Box[T]:
            def __init__(self, item: T):
                self.item = item
            def {method}(self) -> {result_type}:
                return {body}
        def render(values: list[Box[int]]) -> str:
            local = Box[bool](True)
            return repr(({operation}(values[0]), {operation}(local)))
    ''', tmp_path, entry_point="render")
    try:
        host_type = library.parameters[0].value_type.item_type.host_model
        assert library.render([host_type(4)]) == expected
        with pytest.raises(TypeError, match="exact Box"):
            library.render([{"item": 4}])
    finally:
        library.close()


@pytest.mark.parametrize("method, diagnostic", [
    ("@staticmethod\n    def __len__() -> int: return 1", "instance __len__ method"),
    ("@classmethod\n    def __len__(cls) -> int: return 1", "instance __len__ method"),
    ("@property\n    def __len__(self) -> int: return 1", "instance __len__ method"),
    ("__len__ = 2", "instance __len__ method"),
    ("def __len__(self) -> float: return 1.0", "__len__ must return an integer"),
    ("def __len__(self) -> str: return '1'", "__len__ must return an integer"),
    ("def __len__(self, required: int) -> int: return required", "__len__ is missing required"),
    ("def __len__(self, *, required: int) -> int: return required", "__len__ is missing required"),
])
def test_unsupported_length_protocol_is_diagnosed(method, diagnostic):
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm("class Sized:\n    " + method
                       + "\ndef main() -> int:\n    return len(Sized())\n")


def test_erased_length_requires_narrowing():
    with pytest.raises(LLVMUnsupported, match="concrete builtin collection or application class"):
        transpile_llvm('''
            class Sized:
                def __len__(self) -> int:
                    return 2
            def measure(value: object) -> int:
                return len(value)
            def main() -> int:
                return measure(Sized())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["Sized", "list"])
def test_length_through_nullable_and_closed_union_receivers(tmp_path, optimize, name):
    source = '''
        from typing import List
        from pyjs.native import gc_collect, gc_set_threshold
        class Sized:
            def __init__(self, size: int):
                self.size = size
            def __len__(self) -> int:
                gc_collect()
                return self.size
        class Child(Sized):
            def __len__(self) -> int:
                gc_collect()
                return self.size * 2
        def optional(value: Sized | None) -> int:
            try:
                return len(value)
            except TypeError:
                return -10
        def union(value: Sized | str | List[int] | None) -> int:
            try:
                return len(value)
            except TypeError:
                return -20
        def main() -> str:
            gc_set_threshold(1)
            return repr([optional(None), optional(Sized(2)), optional(Child(3)),
                         union(None), union(Sized(4)), union(Child(5)),
                         union("aé😀"), union([1, 2])])
    '''.replace("Sized", name)
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
