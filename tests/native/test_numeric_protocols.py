import pytest

from pyjs.analysis.objects import Function
from pyjs.analysis.source import analyze_source
from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_conversions_dispatch_application_protocols(optimize):
    # Preserved foundation fixture, extended with typed aliases and unions.
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Number:
            def __init__(self, value: int): self.value = value
            def __int__(self) -> int:
                gc_collect()
                return self.value
            def __float__(self) -> float:
                gc_collect()
                return self.value + 0.5
        class Shifted(Number):
            def __int__(self) -> int: return super().__int__() + 1
            def __float__(self) -> float: return super().__float__() + 1.0
        class Indexed:
            def __init__(self, value: int): self.value = value
            def __index__(self) -> int:
                gc_collect()
                return self.value
        def integer(value: Number) -> int: return int(value)
        def floating(value: Number) -> float: return float(value)
        def mixed(value: Number | Indexed | int | None) -> str:
            try: return repr((int(value), float(value)))
            except TypeError: return 'none'
        def main() -> str:
            gc_set_threshold(1)
            return repr((integer(Shifted(20)), floating(Shifted(19)),
                         int(Indexed(10)), float(Indexed(10)),
                         mixed(Number(3)), mixed(Indexed(4)), mixed(5), mixed(None)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("conversion,method,result", [("int", "__int__", "7"),
                                                     ("float", "__float__", "7.5")])
@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_protocol_priority_disabled_methods_and_side_effects(conversion, method, result, optimize):
    comparison = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        events: list[str] = []
        class Indexed:
            def __index__(self) -> int:
                events.append('index')
                gc_collect()
                return 3
        class Primary(Indexed):
            def {method}(self) -> {'int' if conversion == 'int' else 'float'}:
                events.append('primary')
                gc_collect()
                return {result}
        class Disabled(Primary):
            {method} = None
        class Restored(Disabled):
            def {method}(self) -> {'int' if conversion == 'int' else 'float'}:
                events.append('restored')
                return {result}
        class Bad(Indexed):
            def {method}(self) -> str:
                events.append('bad')
                gc_collect()
                return 'wrong'
        class Raising(Indexed):
            def {method}(self) -> {'int' if conversion == 'int' else 'float'}:
                events.append('raising')
                raise ValueError('callback')
        def convert(value: Indexed) -> str:
            try: return str({conversion}(value))
            except TypeError: return 'type'
            except ValueError: return 'value'
        def make() -> Indexed:
            events.append('make')
            return Primary()
        def main() -> str:
            gc_set_threshold(1)
            values = [convert(Indexed()), convert(make()), convert(Disabled()),
                      convert(Restored()), convert(Bad()), convert(Raising()), convert(Primary())]
            gc_collect()
            return repr(values) + repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("conversion,method,result,annotation", [("int", "__int__", "7", "int"),
                                                              ("float", "__float__", "7.5", "float")])
def test_numeric_protocols_ignore_instance_fields_and_support_static_defaults(conversion, method, result, annotation):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        def fake() -> {annotation}: return {result} + 2
        class Value:
            def __init__(self): self.{method}: Callable[[], {annotation}] = fake
            def {method}(self, extra: int = 1) -> {annotation}: return {result} + extra
        class Static:
            @staticmethod
            def {method}(extra: int = 3) -> {annotation}: return {result} + extra
        def main() -> str:
            value = Value()
            return repr(({conversion}(value), value.{method}(), {conversion}(Static())))
    ''', sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("conversion", ["int", "float"])
@pytest.mark.parametrize("return_type,value", [("float", "2.5"), ("str", "'x'"), ("None", "None")])
def test_bad_index_result_is_not_truncated_or_parsed(conversion, return_type, value):
    result = LLVM().assert_matches_python(f'''
        class Value:
            def __index__(self) -> {return_type}: return {value}
        def main() -> str:
            try: return str({conversion}(Value()))
            except TypeError: return 'type'
    ''')
    assert not result.native.stderr


def test_numeric_protocols_distinguish_absent_disabled_and_boolean_index_results():
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        def fake_int() -> int: return 9
        def fake_float() -> float: return 9.5
        class Empty: pass
        class Fields:
            def __init__(self):
                self.__int__: Callable[[], int] = fake_int
                self.__float__: Callable[[], float] = fake_float
        class Disabled:
            __index__ = None
        class Boolean:
            def __index__(self) -> bool: return True
        def convert(value: Empty | Fields | Disabled | Boolean) -> str:
            rows: list[str] = []
            try: rows.append(str(int(value)))
            except TypeError: rows.append('bad int')
            try: rows.append(str(float(value)))
            except TypeError: rows.append('bad float')
            return repr(rows)
        def main() -> str:
            return repr((convert(Empty()), convert(Fields()), convert(Disabled()), convert(Boolean())))
    ''', sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_numeric_protocol_reachability_does_not_analyze_unused_fallback():
    source = '''
        class Value:
            def __int__(self) -> int: return 7
            def __index__(self) -> int: return invalid_name()
            def unrelated(self) -> int: return another_invalid_name()
        def main() -> int: return int(Value())
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        methods = {obj.name for obj in analysis.entry_point.compilation_objects
                   if isinstance(obj, Function) and obj.cls is not None and obj.cls.name == "Value"}
        assert methods == {"__int__"}


@pytest.mark.parametrize("conversion,method,annotation", [("int", "__int__", "int"),
                                                        ("float", "__float__", "float")])
@pytest.mark.parametrize("inherited", [False, True], ids=["direct", "inherited"])
def test_disabled_numeric_protocol_does_not_reach_dead_methods(conversion, method, annotation, inherited):
    base = f'''
class Base:
    def {method}(self) -> {annotation}: return undefined_primary()
    def __index__(self) -> int: return undefined_fallback()
''' if inherited else ''
    source = base + f'''
class Value{'(Base)' if inherited else ''}:
    {method} = None
    {'' if inherited else 'def __index__(self) -> int: return undefined_fallback()'}
def main() -> str:
    try: return str({conversion}(Value()))
    except TypeError: return 'disabled'
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        methods = {obj.name for obj in analysis.entry_point.compilation_objects
                   if isinstance(obj, Function) and obj.cls is not None and obj.cls.name in {"Base", "Value"}}
        assert not methods
    result = LLVM().assert_matches_python(source, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_noncallable_primary_keeps_fallback_dead_before_type_error():
    source = '''
class Value:
    __int__ = 3
    def __index__(self) -> int: return undefined_fallback()
def main() -> str:
    try: return str(int(Value()))
    except TypeError: return 'noncallable'
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        methods = {obj.name for obj in analysis.entry_point.compilation_objects
                   if isinstance(obj, Function) and obj.cls is not None and obj.cls.name == "Value"}
        assert not methods
    result = LLVM().assert_matches_python(source, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("method,annotation", [("__int__", "int"), ("__float__", "float")])
@pytest.mark.parametrize("declaration", ["@property", "@classmethod"])
def test_numeric_conversion_descriptor_boundary_is_located(method, annotation, declaration):
    source = f'''
class Value:
    {declaration}
    def {method}({'cls' if declaration == '@classmethod' else 'self'}) -> {annotation}:
        return {'1.0' if annotation == 'float' else '1'}
def main() -> str:
    return str({annotation}(Value()))
'''
    with pytest.raises(LLVMUnsupported, match="instance or static method") as caught:
        transpile_llvm(source)
    assert caught.value.node.lineno > 0


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_protocols_preserve_represented_and_enum_results(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum
        from pyjs import int8, int64, float32
        class Code(IntEnum):
            VALUE = 7
        class Small:
            def __int__(self) -> int8: return int8(-120)
            def __float__(self) -> float32: return float32(1.5)
        class Large:
            def __index__(self) -> int64: return int64(9007199254740993)
        class EnumValue:
            def __int__(self) -> Code: return Code.VALUE
        def main() -> str:
            return repr((int(Small()), float(Small()), int(Large()), float(Large()),
                         int(EnumValue()), int(Code.VALUE), float(Code.VALUE),
                         int(int8(-3)), float(int64(7))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("conversion,method,annotation", [("int", "__int__", "int"),
                                                        ("float", "__float__", "float")])
def test_numeric_protocols_support_imported_builtin_aliases(conversion, method, annotation):
    result = LLVM().assert_matches_python(f'''
        from builtins import {conversion} as convert
        class Value:
            def {method}(self) -> {annotation}: return {"3.5" if annotation == "float" else "3"}
        def main() -> str:
            return str(convert(Value()))
    ''')
    assert not result.native.stderr


@pytest.mark.parametrize("conversion,method,annotation", [("int", "__int__", "int"),
                                                        ("float", "__float__", "float")])
def test_numeric_protocols_work_through_lazy_map_adapters(conversion, method, annotation):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int): self.value = value
            def {method}(self) -> {annotation}:
                gc_collect()
                if self.value == 0: raise ValueError('zero')
                return {annotation}(self.value)
        def main() -> str:
            gc_set_threshold(1)
            cursor = map({conversion}, [Value(2), Value(0), Value(3)])
            first = next(cursor)
            try: next(cursor)
            except ValueError: pass
            return repr((first, next(cursor)))
    ''', sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("conversion,method", [("int", "__int__"), ("float", "__float__")])
@pytest.mark.parametrize("annotation,result", [("object", "3"), ("int | str", "'x'")])
def test_numeric_protocol_erased_or_union_results_are_checked(conversion, method, annotation, result):
    comparison = LLVM().assert_matches_python(f'''
class Value:
    def {method}(self) -> {annotation}: return {result}
def main() -> str:
    try:
        return str({conversion}(Value()))
    except TypeError:
        return "invalid"
''', sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("compile,error", [(transpile_jvm, JVMUnsupported),
                                          (transpile_webassembly, WebAssemblyUnsupported)],
                         ids=["jvm", "wasm"])
@pytest.mark.parametrize("conversion,method,annotation", [("int", "__int__", "int"),
                                                        ("float", "__float__", "float")])
def test_other_native_targets_keep_explicit_application_conversion_boundary(compile, error, conversion, method, annotation):
    with pytest.raises(error, match="construction requires a number.*at line"):
        compile(f'''
class Value:
    def {method}(self) -> {annotation}: return {"3.5" if annotation == "float" else "3"}
def main() -> {annotation}:
    return {conversion}(Value())
''')
