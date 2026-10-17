"""Literal queries preserve ordinary read order; unsupported lookup is explicit."""

from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("query", ['hasattr(value, NAME)', 'getattr(value, NAME, 9)', 'getattr(value, NAME)'])
@pytest.mark.parametrize("name", ["__value", "_Box__value", "__method", "_Box__method"])
def test_private_literal_queries_diagnose_instead_of_using_source_names(query, name):
    expression = query.replace("NAME", repr(name))
    with pytest.raises((CompilationError, LLVMUnsupported), match="private name spellings"):
        transpile_llvm(dedent(f'''
            class Box:
                def __init__(self): self.__value = 7
                def __method(self) -> int: return 8
            def main() -> str:
                value = Box()
                return str({expression})
        '''))


@pytest.mark.parametrize("query", ['hasattr(self, "_Box__value")', 'getattr(self, "__value", 9)'])
def test_inherited_private_queries_inside_class_and_underscored_owner(query):
    with pytest.raises((CompilationError, LLVMUnsupported), match="private name spellings"):
        transpile_llvm(dedent(f'''
            class _Box:
                def __init__(self): self.__value = 7
            class Child(_Box):
                def query(self) -> str: return str({query})
            def main() -> str: return Child().query()
        '''))


@pytest.mark.parametrize("query", ['hasattr(value, "_Child__value")', 'getattr(value, "_Child__value", 9)'])
def test_late_subclass_private_spelling_cannot_be_folded_missing(query):
    with pytest.raises((CompilationError, LLVMUnsupported), match="private name spellings"):
        transpile_llvm(dedent(f'''
            class Base: pass
            class Child(Base):
                def __init__(self): self.__value = 7
            def query(value: Base) -> str: return str({query})
            def main() -> str: return query(Child())
        '''))


@pytest.mark.parametrize("optimize", [0, 2])
def test_public_underscore_dunder_and_private_direct_read_controls(optimize):
    result = LLVM().assert_matches_python('''
        class Box:
            def __init__(self):
                self.__value = 7
                self._value = 8
                self._Alien__value = 9
            def read(self) -> int: return self.__value
            def __len__(self) -> int: return 3
        def main() -> str:
            value = Box()
            return repr((value.read(), getattr(value, "_value"),
                         getattr(value, "_Alien__value"), hasattr(value, "__len__"),
                         getattr(value, "__len__")()))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_post_reachability_query_diagnostic_has_module_location():
    source = dedent('''\
        class Base: pass
        class Child(Base):
            def __init__(self): self.value = 4

        def query(value: Base) -> int:
            return getattr(value, "value", 2)

        def main() -> int: return query(Child())
    ''')
    with pytest.raises(LLVMUnsupported, match="absent on every reached subclass") as caught:
        transpile_llvm(source, filename="attribute_location.py")
    assert caught.value.__notes__ == [
        "Source location: attribute_location.py:6:12 (query; reported line above is function-relative)"]


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_attributes_inheritance_defaults_and_presence(optimize):
    result = LLVM().assert_matches_python('''
        class Base:
            def __init__(self, value: int): self.value = value
            def method(self) -> int: return self.value
        class Child(Base): pass
        class Extra(Base):
            def extra(self) -> int: return 5
        def present(value: Base | None) -> tuple[bool, bool, bool, bool]:
            return (hasattr(value, "value"), hasattr(value, "method"),
                    hasattr(value, "extra"), hasattr(value, "missing"))
        def main() -> str:
            value = Child(40)
            return repr((getattr(value, "value"), getattr(value, "missing", 2),
                getattr(value, "value", 99), getattr(value, "method")(),
                present(value), present(None), present(Extra(4))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_receiver_order_gc_identity_and_errors(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: str): self.value = value
            def method(self) -> str: return self.value
        def receiver(events: list[str], fail: bool) -> Box:
            events.append("receiver")
            if fail: raise ValueError("receiver failed")
            return Box("kept" + str(len(events)))
        def default(events: list[str], fail: bool) -> Box:
            events.append("default")
            gc_collect()
            if fail: raise ValueError("default failed")
            return Box("fallback")
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            rows: list[str] = []
            for fail_receiver in [False, True]:
                for fail_default in [False, True]:
                    try:
                        rows.append(getattr(receiver(events, fail_receiver), "value",
                                            default(events, fail_default)))
                    except ValueError as error:
                        rows.append(str(error))
            fallback = default(events, False)
            same = getattr(receiver(events, False), "missing", fallback) is fallback
            callback = getattr(receiver(events, False), "method", default(events, False))
            gc_collect()
            return repr((rows, events, same, callback()))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_property_without_default_keeps_virtual_dispatch_and_exceptions(optimize):
    result = LLVM().assert_matches_python('''
        class Base:
            @property
            def value(self) -> str:
                print("base getter")
                return "base"
        class Child(Base):
            @property
            def value(self) -> str:
                print("child getter")
                raise AttributeError("getter failed")
        def query(value: Base) -> str:
            try: return getattr(value, "value")
            except AttributeError as error: return str(error)
        def main() -> str:
            return query(Base()) + query(Child())
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_import_aliases_shadowing_and_optional_capture(optimize):
    result = LLVM().assert_matches_python('''
        import builtins
        from builtins import getattr as read, hasattr as present
        from collections.abc import Callable
        from pyjs.native import gc_collect
        class Box:
            def __init__(self): self.value = 5
        def shadow(hasattr: Callable[[Box, str], bool]) -> bool:
            return hasattr(Box(), "value")
        def main() -> str:
            value: Box | None = Box()
            assert value is not None
            query = lambda: present(value, "value")
            stream = (present(value, "value") for _ in range(2))
            first = (read(value, "value"), query(), next(stream),
                     builtins.getattr(value, "value"), builtins.hasattr(value, "value"))
            value = None
            gc_collect()
            return repr((first, query(), next(stream), shadow(lambda box, name: False)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_portable_fields_and_default_mutation_before_read(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int64
        class Box:
            def __init__(self): self.value = int64(9007199254740993)
        def change(value: Box) -> int:
            value.value += int64(2)
            return 0
        def main() -> str:
            value = Box()
            result = getattr(value, "value", change(value))
            missing = getattr(value, "missing", int64(9007199254740997))
            return repr((result, value.value, missing))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_presence_receiver_effects_and_none_builtin_attributes(optimize):
    result = LLVM().assert_matches_python('''
        class Box:
            constant = 4
            def method(self) -> int: return 1
        def receiver(fail: bool) -> Box:
            print("receiver")
            if fail: raise LookupError("failed")
            return Box()
        def main() -> str:
            first = hasattr(receiver(False), "method")
            try:
                hasattr(receiver(True), "missing")
            except LookupError:
                print("caught")
            return repr((first, hasattr(None, "__class__"), hasattr(None, "__repr__"),
                         hasattr(None, "missing"), getattr(Box(), "constant")))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_deferred_getattr_does_not_inherit_an_optional_capture_proof():
    with pytest.raises(CompilationError, match="requires a concrete instance"):
        transpile_llvm('''
            class Box:
                def __init__(self): self.value = 1
            def main() -> int:
                value: Box | None = Box()
                assert value is not None
                query = lambda: getattr(value, "missing", 2)
                value = None
                return query()
        ''')


@pytest.mark.parametrize("expression, message", [
    ('getattr(value, name)', 'string literal'),
    ('hasattr(value, name)', 'literal attribute'),
    ('getattr(value, "unknown")', "not defined"),
    ('getattr(value, "property_value", 1)', 'property AttributeError'),
    ('hasattr(value, "property_value")', 'property AttributeError'),
    ('getattr(value=value, name="value")', 'positional'),
    ('hasattr(value=value, name="value")', 'positional'),
])
def test_query_diagnostics(expression, message):
    with pytest.raises((CompilationError, LLVMUnsupported), match=message):
        transpile_llvm(dedent(f'''
            class Box:
                def __init__(self): self.value = 1
                @property
                def property_value(self) -> int: raise AttributeError("missing")
            def main() -> str:
                value = Box()
                name = "value"
                return str({expression})
        '''))


@pytest.mark.parametrize("query", ['hasattr(value, "value")', 'getattr(value, "value", 0)'])
def test_rejects_dynamic_lookup(query):
    with pytest.raises((CompilationError, LLVMUnsupported), match="ordinary attribute lookup"):
        transpile_llvm(dedent(f'''
            class Box:
                def __getattr__(self, name: str) -> int: return 3
            def main() -> str:
                value = Box()
                return str({query})
        '''))


@pytest.mark.parametrize("initializer", [
    'if flag: self.value = 1',
    'print(hasattr(self, "value")); self.value = 1',
])
def test_partial_initialization_is_not_assumed_present(initializer):
    with pytest.raises(LLVMUnsupported, match="initialized before self can escape"):
        transpile_llvm(dedent(f'''
            class Box:
                def __init__(self, flag: bool):
                    {initializer}
            def main() -> bool: return hasattr(Box(False), "value")
        '''))


def test_missing_default_cannot_hide_reached_subclass_member():
    with pytest.raises(LLVMUnsupported, match="absent on every reached subclass"):
        transpile_llvm('''
            class Base: pass
            class Child(Base):
                def __init__(self): self.value = 4
            def query(value: Base) -> int: return getattr(value, "value", 2)
            def main() -> int: return query(Child())
        ''')


def test_constructor_setter_cannot_expose_an_uninitialized_field():
    with pytest.raises(LLVMUnsupported, match="initialized before self can escape"):
        transpile_llvm('''
            class Box:
                def __init__(self):
                    self.trigger = 1
                    self.value = 2
                @property
                def trigger(self) -> int: return 0
                @trigger.setter
                def trigger(self, value: int) -> None:
                    print(hasattr(self, "value"))
            def main() -> bool: return hasattr(Box(), "value")
        ''')


@pytest.mark.parametrize("expression", ['getattr(value, "value", 0)', 'hasattr(value, "value")'])
def test_reached_subclass_property_is_not_silently_skipped(expression):
    with pytest.raises((CompilationError, LLVMUnsupported), match="property AttributeError"):
        transpile_llvm(dedent(f'''
            class Base:
                value = 1
            class Child(Base):
                @property
                def value(self) -> int: raise AttributeError("absent")
            def query(value: Base) -> str: return str({expression})
            def main() -> str: return query(Child())
        '''))
