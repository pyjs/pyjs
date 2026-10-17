import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.objects import Function
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM

PROTOCOLS = [("int", "__int__", "int", "7"),
             ("float", "__float__", "float", "7.5"),
             ("round", "__round__", "int", "7"),
             ("int", "__index__", "int", "7"),
             ("float", "__index__", "int", "7")]


@pytest.mark.parametrize("conversion,method,annotation,value", PROTOCOLS)
@pytest.mark.parametrize("optimize", [0, 2])
def test_noncallable_override_hides_inherited_protocol(conversion, method, annotation, value, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def {method}(self) -> {annotation}:
                gc_collect()
                return {value}
        class Disabled(Base):
            {method} = 3
        class Restored(Disabled):
            @staticmethod
            def {method}() -> {annotation}: return {value} + 1
        def convert(value: Base) -> str:
            try: return str({conversion}(value))
            except TypeError: return 'disabled'
        def main() -> str:
            gc_set_threshold(1)
            return repr((convert(Base()), convert(Disabled()), convert(Restored())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("conversion,method,annotation,value", PROTOCOLS[:2])
@pytest.mark.parametrize("declaration", ["3", "False", "'disabled'"])
def test_noncallable_override_does_not_retain_hidden_bodies(conversion, method, annotation, value, declaration):
    source = f'''
class Base:
    def {method}(self) -> {annotation}: return undefined_primary()
    def __index__(self) -> int: return undefined_fallback()
class Disabled(Base):
    {method} = {declaration}
def main() -> str:
    try: return str({conversion}(Disabled()))
    except TypeError: return 'disabled'
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        methods = {obj.name for obj in analysis.entry_point.compilation_objects
                   if isinstance(obj, Function) and obj.cls is not None and obj.cls.name in {"Base", "Disabled"}}
        assert not methods
    result = LLVM().assert_matches_python(source, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("conversion,method,annotation,value", PROTOCOLS)
@pytest.mark.parametrize("inherited", [False, True], ids=["direct", "override"])
@pytest.mark.parametrize("static", [False, True], ids=["instance", "static"])
def test_callable_aliases_have_a_located_compile_boundary(conversion, method, annotation, value, inherited, static):
    source = f'''
class Base:
    def {method}(self) -> {annotation}: return {value}
class Value{'(Base)' if inherited else ''}:
    {'@staticmethod' if static else ''}
    def replacement({'' if static else 'self'}) -> {annotation}: return {value} + 1
    {method} = replacement
def main() -> str:
    try: return str({conversion}(Value()))
    except TypeError: return 'incorrect noncallable diagnosis'
'''
    if conversion == "round":
        with pytest.raises(CompilationError, match="instance or static __round__ method.*PYJS2001") as caught:
            transpile_llvm(source)
        assert caught.value.lineno > 0
    else:
        with pytest.raises(LLVMUnsupported, match=f"native {method} requires a modeled class method.*at line") as caught:
            transpile_llvm(source)
        assert caught.value.node.lineno > 0


def test_callable_descriptor_is_not_misdiagnosed_as_noncallable():
    source = '''
class Descriptor:
    def __get__(self, instance: object, owner: object) -> object: return 3
class Value:
    __int__ = Descriptor()
def main() -> str:
    try: return str(int(Value()))
    except TypeError: return 'not a compile-time callability decision'
'''
    with pytest.raises(LLVMUnsupported, match="requires a modeled class method.*at line"):
        transpile_llvm(source)
