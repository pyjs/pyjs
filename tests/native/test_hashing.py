import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_receiver_hash_and_repr_leave_unrelated_methods_unreached(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Other:
            def __hash__(self) -> int:
                return missing_name()
            def __repr__(self) -> str:
                return missing_name()
        class Base:
            pass
        class Child(Base):
            def __hash__(self) -> int:
                gc_collect()
                return -1
            def __repr__(self) -> str:
                gc_collect()
                return 'child'
        def read(value: Base) -> str:
            return str(value) + '|' + str(value.__hash__())
        def packed(value: Base) -> str:
            return repr([value])
        def main() -> str:
            gc_set_threshold(1)
            other = Other()
            read(Base())
            child = Child()
            return str((read(child), packed(child), (1).__hash__(),
                        'q'.__hash__() == hash('q'),
                        (1, 'a').__hash__() == hash((1, 'a'))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_builtin_hash_keeps_runtime_helpers_without_hash_call(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64, float32
        class Item:
            pass
        def main() -> str:
            value = Item()
            values = [1]
            output = [str(value.__hash__() == value.__hash__()),
                      str((-1).__hash__()), str((1.5).__hash__()), str(True.__hash__()),
                      str(int8(-1).__hash__()), str(int64(-1).__hash__()), str(float32(1.5).__hash__())]
            try:
                values.__hash__()
            except TypeError as error:
                output.append(str(error))
            return '|'.join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_concrete_boolean_hash_method_keeps_boolean_result(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Item:
            def __hash__(self) -> bool:
                return True
        def main() -> str:
            value = Item()
            return str(value.__hash__()) + '|' + str(hash(value))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_hash_protocol_keeps_existing_portable_integer_override(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int64
        class Item:
            def __hash__(self) -> int64:
                return int64(-1)
        def main() -> str:
            value = Item()
            return str(value.__hash__()) + '|' + str(hash(value))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("result, value, diagnostic", [
    ("bool", "True", "explicit __hash__ overrides must preserve the int return signature"),
    ("int64", "int64(-1)", "declarations require matching storage representations"),
])
def test_explicit_default_hash_preserves_the_declared_return_boundary(result, value, diagnostic):
    from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm(f'''
            from pyjs import int64
            class Base:
                pass
            class Child(Base):
                def __hash__(self) -> {result}:
                    return {value}
            def direct(value: Base) -> int:
                return value.__hash__()
            def main() -> str:
                return str(direct(Child()))
        ''')


def test_other_backends_keep_explicit_default_hash_boundaries():
    from pyjs.java import JVMUnsupported, transpile_jvm
    from pyjs.webassembly.transpiler import WebAssemblyUnsupported, transpile_webassembly
    source = '''
        class Item:
            pass
        def main() -> int:
            return Item().__hash__()
    '''
    with pytest.raises(JVMUnsupported, match="unsupported JVM scalar operation __hash__"):
        transpile_jvm(source)
    with pytest.raises(WebAssemblyUnsupported, match="WebAssembly call target __hash__ is not implemented"):
        transpile_webassembly(source)


def test_authored_hash_base_view_still_requires_matching_override_storage():
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.native.llvm import transpile_llvm
    with pytest.raises(CompilationError, match="Override Child.__hash__ changes the represented storage contract"):
        transpile_llvm('''
            from pyjs import int64
            class Base:
                def __hash__(self) -> int:
                    return -1
            class Child(Base):
                def __hash__(self) -> int64:
                    return int64(-1)
            def direct(value: Base) -> int:
                return value.__hash__()
            def main() -> str:
                return str(direct(Child()))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_default_hash_dispatch_preserves_method_semantics(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            pass
        class Hashed(Base):
            def __hash__(self) -> int:
                gc_collect()
                return -1
        class Disabled(Base):
            __hash__ = None
        class Equal(Base):
            def __eq__(self, other: Equal) -> bool:
                return True
        class Inherited(Base):
            def identity(self) -> int:
                return super().__hash__()
        def direct(value: Base) -> int:
            return value.__hash__()
        def main() -> str:
            gc_set_threshold(1)
            value = Base()
            inherited = Inherited()
            output = [str(value.__hash__() == hash(value)),
                      str(inherited.identity() == hash(inherited)),
                      str(direct(Hashed())), str(hash(Hashed()))]
            try:
                direct(Disabled())
            except TypeError as error:
                output.append(str(error))
            try:
                direct(Equal())
            except TypeError as error:
                output.append(str(error))
            gc_collect()
            output.append(str(direct(value) == hash(value)))
            return '|'.join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_default_hash_dispatches_nullable_and_union_receivers(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            pass
        class Child(Base):
            def __hash__(self) -> int:
                gc_collect()
                return -1
        def optional(value: Base | None) -> int:
            return value.__hash__()
        def union(value: Base | int | str) -> int:
            return value.__hash__()
        def main() -> str:
            gc_set_threshold(1)
            value = Base()
            return str((optional(value) == hash(value), optional(None) == hash(None),
                        optional(Child()), union(value) == hash(value),
                        union(Child()), union(-1), union('text') == hash('text')))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("base, arguments", [
    ("class Base:\n    __hash__ = None", ""),
    ("class Base:\n    def __eq__(self, other: Base) -> bool:\n        return True", ""),
    ("from dataclasses import dataclass\n@dataclass\nclass Base:\n    value: int", "1"),
], ids=["explicit-none", "equality", "dataclass"])
def test_super_hash_honors_disabled_lexical_bases(tmp_path, optimize, base, arguments):
    source = base + f'''
class Child(Base):
    def __hash__(self) -> int:
        return super().__hash__() + 1
    def parent_hash(self) -> int:
        parent = super()
        return parent.__hash__()
def main() -> str:
    value = Child({arguments})
    output: list[str] = []
    try:
        output.append(str(value.parent_hash()))
    except TypeError as error:
        output.append(str(error))
    try:
        output.append(str(hash(value)))
    except TypeError as error:
        output.append(str(error))
    return '|'.join(output)
'''
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("options", ["frozen=True", "unsafe_hash=True"])
def test_super_hash_keeps_generated_dataclass_boundary(options):
    from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
    with pytest.raises(LLVMUnsupported, match="generated dataclass hashing is not implemented"):
        transpile_llvm(f'''
            from dataclasses import dataclass
            @dataclass({options})
            class Base:
                value: int
            class Child(Base):
                def parent_hash(self) -> int:
                    return super().__hash__()
            def main() -> str:
                return str(Child(1).parent_hash() == Child(1).parent_hash())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_hash_selects_runtime_class_protocol_through_base_and_tuple(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            pass
        class Hashed(Base):
            def __hash__(self) -> int:
                gc_collect()
                return 71
        class Disabled(Hashed):
            __hash__ = None

        def inspect(value: Base) -> str:
            try:
                return str(hash(value) == 71) + str(hash((value,)) == hash((71,)))
            except TypeError as error:
                return str(error)
        def narrow(value: int | str) -> str:
            if isinstance(value, int):
                return str(hash(value))
            return value
        def main() -> str:
            gc_set_threshold(1)
            return inspect(Hashed()) + inspect(Disabled()) + narrow(True) + narrow(2)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("decorator", ["staticmethod", "classmethod"])
def test_hash_has_a_focused_descriptor_boundary(decorator):
    from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
    parameter = "cls" if decorator == "classmethod" else ""
    with pytest.raises(LLVMUnsupported, match="hash requires instance special methods"):
        transpile_llvm(f'''
            class Item:
                @{decorator}
                def __hash__({parameter}) -> int:
                    return 7
            def main() -> int:
                return hash(Item())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_hashes_share_python_equality_invariants(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def main() -> str:
            output: list[str] = []
            for value in [0, 1, -1, 2**61 - 1, 2**61, -(2**61), 2**63 - 1, -(2**63)]:
                output.append(str(hash(value)))
            for number in [0.0, -0.0, 1.0, -1.0, 1.5, -1.5, 1e100, -1e100, 5e-324, -5e-324]:
                output.append(str(hash(number)))
            output.append(str(hash(float('inf'))))
            output.append(str(hash(float('-inf'))))
            output.append(str(hash(True) == hash(1) == hash(1.0)))
            output.append(str(hash(False) == hash(0) == hash(-0.0)))
            return '|'.join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_immutable_collection_hashes_cache_only_successful_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self):
                self.calls = 0
            def __hash__(self) -> int:
                self.calls += 1
                gc_collect()
                if self.calls == 1:
                    raise ValueError('retry')
                return 7

        def main() -> str:
            gc_set_threshold(1)
            item = Item()
            values = (item, 'text', (1, 2))
            try:
                hash(values)
            except ValueError:
                pass
            before = hash(values)
            after = hash(values)
            results = [before == after, item.calls == 2,
                       hash((True, 2)) == hash((1, 2.0)),
                       hash(frozenset([1, 2, 3])) == hash(frozenset([3, 2, 1])),
                       hash((frozenset([1, 2]), 'x')) == hash((frozenset([2, 1]), 'x'))]
            try:
                hash(([1], 2))
            except TypeError as error:
                return str(results) + str(error)
            return 'missing error'
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_hash_calls_keep_text_identity_and_custom_protocols(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Identity:
            pass
        class Negative:
            def __hash__(self) -> int:
                gc_collect()
                return -1
        class Boolean:
            def __hash__(self) -> bool:
                gc_collect()
                return True
        class Unhashable:
            def __eq__(self, other: Unhashable) -> bool:
                return True

        def main() -> str:
            gc_set_threshold(1)
            item = Identity()
            before = hash(item)
            gc_collect()
            result = [hash('a' + str(1)) == hash('a1'), hash(b'a\\0b') == hash(b'a\\0b'),
                      before == hash(item), hash(Negative()) == -2,
                      hash(Boolean()) == hash(True)]
            try:
                hash(Unhashable())
            except TypeError as error:
                return str(result) + '/' + str(error)
            return 'missing error'
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
