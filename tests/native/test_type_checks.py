import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    ASSERT_INSTANCE_STATE_CONTRACT,
    ISINSTANCE_LITERAL_TUPLE_CONTRACT,
)


def test_shared_literal_tuple_instance_contract():
    result = LLVM().assert_matches_python(ISINSTANCE_LITERAL_TUPLE_CONTRACT.source)
    assert result.native.returncode == 0


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_instance_assertion_contract(optimize):
    result = LLVM().assert_matches_python(
        ASSERT_INSTANCE_STATE_CONTRACT.source, optimize=optimize,
    )
    assert result.native.returncode == 0, ASSERT_INSTANCE_STATE_CONTRACT.failure(
        result.native.returncode,
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_isinstance_targets_effects_narrowing_and_runtime_tags(optimize):
    result = LLVM().assert_matches_python('''
        from builtins import isinstance as check
        from pyjs.native import gc_collect, gc_set_threshold
        class Base: pass
        class Child(Base): pass
        class Other: pass
        def make(events: list[int]) -> Child:
            events.append(1)
            gc_collect()
            return Child()
        def classify(value: int | float | str | None) -> str:
            if isinstance(value, (int, str)):
                return str(value)
            return "other"
        def erased(value: object) -> bool:
            return isinstance(value, (str, (Other, Base)))
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            assert check(make(events), (str, ((), Base)))
            assert not check(make(events), ())
            assert not check(make(events), (Other, (str,)))
            assert events == [1, 1, 1]
            assert not isinstance(2, (float, str))
            assert not isinstance(2, float)
            assert isinstance(True, (int,)) and not isinstance(True, (float,))
            values: list[int] = []
            assert isinstance(values, (dict, list))
            return repr((classify(3), classify(2.0), classify("yes"), classify(None),
                         erased(Child()), erased(Other()), erased(None), erased(2.0)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_structural_parameter_queries_use_actual_class_not_assignment_relation(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Shape:
            __pyjs_structural__ = True
            def area(self) -> int: return 0
        class Child(Shape):
            def area(self) -> int: return 5
        class Square:
            def area(self) -> int: return 4
        def erased(value: object) -> bool:
            return isinstance(value, Shape)
        def query(value: Shape) -> tuple[bool, bool, bool, bool]:
            gc_collect()
            return (isinstance(value, Square), isinstance(value, Shape),
                    isinstance(value, (str, Shape)), isinstance(value, object))
        def optional(value: Shape | None) -> bool:
            return isinstance(value, Shape)
        def branch(value: Shape | None) -> str:
            if isinstance(value, (str, Shape)):
                return "shape"
            return "none" if value is None else "other"
        def main() -> str:
            gc_set_threshold(1)
            square, child, shape = Square(), Child(), Shape()
            first = erased(square)
            return repr((first, query(square), query(child), query(shape),
                         optional(square), optional(child), optional(shape), optional(None),
                         branch(square), branch(child), branch(shape), branch(None)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("target", ["Square", "Shape"])
@pytest.mark.parametrize("subclass", ["", "class Child(Shape): pass"])
def test_structural_query_without_concrete_headers_is_a_focused_diagnostic(target, subclass):
    inherited_query = " + int(query(Child()))" if subclass else ""
    with pytest.raises(LLVMUnsupported, match="requires runtime class identity"):
        transpile_llvm(f'''
class Shape:
    __pyjs_structural__ = True
    def area(self) -> int: return 0
class Square:
    def area(self) -> int: return 4
{subclass}
def query(value: Shape) -> bool:
    return isinstance(value, {target})
def main() -> int:
    return int(query(Square())){inherited_query}
''', filename="structural-query.py")


@pytest.mark.parametrize("target", ["Base", "(str, Base)"])
def test_headerless_structural_query_checks_compatible_descendants_and_retains_location(target):
    with pytest.raises(LLVMUnsupported, match="requires runtime class identity") as caught:
        transpile_llvm(f'''
class Shape:
    __pyjs_structural__ = True
    def area(self) -> int: return 0
class Base: pass
class Square(Base):
    def area(self) -> int: return 4
def query(value: Shape) -> bool:
    return isinstance(value, {target})
def main() -> int:
    return int(query(Square()))
''', filename="structural-intersection.py")
    assert caught.value.node is not None
    assert caught.value.node.lineno == 2  # Function-relative analyzed coordinates.


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_issubclass_nominal_classes_and_nested_targets(optimize):
    result = LLVM().assert_matches_python('''
        from builtins import issubclass as check
        class Base: pass
        class Child(Base): pass
        class Other: pass
        def main() -> str:
            return repr((check(Child, Base), check(Child, Child), check(Child, object),
                         check(Child, (str, (Other, Base))), check(Base, Child),
                         check(Other, Base), check(int, float), check(bool, int),
                         check(bool, float), check(list, object), check(list, list),
                         check(dict, list), check(Child, ()), check(tuple, object)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "issubclass(1, int)", "issubclass(int, (str, 42))",
    "issubclass(int)", "issubclass(int, int, str)",
    "issubclass(value=int, value_type=int)",
    "isinstance(value=1, value_type=int)",
    "issubclass(list[int], list)", "issubclass(list, list[int])",
    "isinstance(1, (str, 42))",
    "isinstance([1], (str, list[int]))",
    "isinstance(*(1, int))", "issubclass(*(int, int))",
])
def test_type_check_unsupported_classinfo_has_a_located_diagnostic(expression):
    with pytest.raises(CompilationError):
        transpile_llvm(f"def main() -> int:\n    return int({expression})\n", filename="classinfo.py")


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_classinfo_preserves_portable_subject_representation(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64, float32
        def main() -> str:
            return repr((isinstance(int8(1), (float, int)), isinstance(int64(2), (str, int)),
                         isinstance(float32(3), (int, float))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("target", ["HTMLDivElement", "Element"])
def test_static_subclass_queries_do_not_conflate_mapped_dom_classes(target):
    with pytest.raises(CompilationError, match="mapped DOM class identities"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.html import HTMLDivElement, HTMLSpanElement
def main() -> int:
    return int(issubclass(HTMLSpanElement, {target}))
''', filename="classinfo.py")


@pytest.mark.parametrize("target", ["Element", "HTMLDivElement"])
def test_tuple_isinstance_retains_dom_query_provenance(target):
    source = f'''
from pyjs.web.dom import Element
from pyjs.web.html import HTMLDivElement
from pyjs.web.domx import div
def main() -> int:
    return int(isinstance(div(), (str, {target})))
'''
    if target == "HTMLDivElement":
        with pytest.raises(LLVMUnsupported, match="not concrete DOM interfaces"):
            transpile_llvm(source, filename="classinfo.py")
    else:
        result = LLVM().assert_matches_python(source, sanitizers=("address", "undefined"))
        assert not result.native.stderr


def test_static_subclass_query_does_not_invoke_a_metaclass_hook():
    with pytest.raises(CompilationError, match="metaclass subclass checks"):
        transpile_llvm('''
class Meta(type):
    def __subclasscheck__(cls, subclass: type) -> bool:
        raise AssertionError("must not run during compilation")
class Target(metaclass=Meta): pass
def main() -> int:
    return int(issubclass(int, Target))
''', filename="classinfo.py")


def test_tuple_instance_query_does_not_invoke_a_metaclass_hook():
    with pytest.raises(CompilationError, match="metaclass instance checks"):
        transpile_llvm('''
class Meta(type):
    def __instancecheck__(cls, value: object) -> bool:
        raise AssertionError("must not run during compilation")
class Target(metaclass=Meta): pass
def main() -> int:
    return int(isinstance(1, (str, Target)))
''', filename="classinfo.py")


@pytest.mark.parametrize("binding", ["target = 42", "target: int | str = 42"])
def test_invalid_named_classinfo_in_branch_is_not_an_internal_assertion(binding):
    with pytest.raises(CompilationError, match="runtime class target"):
        transpile_llvm(f'''
def main() -> int:
    {binding}
    value = 1
    if isinstance(value, (str, target)):
        return 2
    return 0
''', filename="classinfo.py")


@pytest.mark.parametrize("expression", ["issubclass(list, Iterable)", "isinstance([1], (str, Iterable))"])
def test_class_queries_do_not_confuse_typing_interfaces_with_runtime_abcs(expression):
    with pytest.raises(CompilationError, match="typing-interface class checks"):
        transpile_llvm(f'''
from collections.abc import Iterable
def main() -> int:
    return int({expression})
''', filename="classinfo.py")


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_class_queries_are_nominal_not_structural(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Shape:
            __pyjs_structural__ = True
            def area(self) -> int: return 0
        class Child(Shape):
            def area(self) -> int: return 5
        class Square:
            def area(self) -> int: return 4
        def erased(value: object) -> bool:
            return isinstance(value, Shape)
        def broad(value: Shape) -> bool:
            return isinstance(value, Child)
        def main() -> str:
            gc_set_threshold(1)
            square = Square()
            child = Child()
            # Erasure forces identity tables, so the concrete query also
            # exercises its vtable path rather than only constant folding.
            first = erased(square)
            gc_collect()
            return repr((issubclass(Square, Shape), issubclass(Child, Shape),
                         isinstance(square, Shape), isinstance(square, (str, Shape)),
                         isinstance(child, Shape), isinstance(child, (str, Shape)),
                         first, erased(child), broad(child), broad(Shape())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
