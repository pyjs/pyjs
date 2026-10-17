import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_exact_classes_and_tagged_integers_narrow_without_confusing_subclasses(optimize):
    result = LLVM().assert_matches_python('''
        from builtins import type as kind
        class Base: pass
        class Child(Base):
            def score(self) -> int: return 7
        class Grandchild(Child): pass
        def query(value: Base) -> int:
            if kind(value) is Base: return 1
            if Child is kind(value): return value.score()
            if kind(value) is not Base:
                return 3 if isinstance(value, Grandchild) else 4
            return 0
        def scalar(value: int | str) -> int:
            if type(value) is int and value > 0:
                return value
            if not (type(value) is not int):
                return value
            if type(value) is str:
                return len(value)
            return 99
        def main() -> str:
            return repr((query(Base()), query(Child()), query(Grandchild()),
                         scalar(5), scalar(-2), scalar("ready"), scalar(True)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_exact_erased_identity_and_once_only_subject_effects(optimize):
    result = LLVM().assert_matches_python('''
        import builtins
        from pyjs.native import gc_collect, gc_set_threshold
        class Item: pass
        class Child(Item): pass
        def query(value: object) -> tuple[bool, bool, bool, bool, bool, bool]:
            gc_collect()
            return (type(value) is Item, type(value) is Child, type(value) is int,
                    type(value) is bool, type(value) is str, type(value) is list)
        def make(events: list[int]) -> Item:
            events.append(1)
            gc_collect()
            return Child()
        def integer(value: object) -> int:
            if type(value) is int: return value
            return 0
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = builtins.type(make(events)) is Child
            second = Item is not builtins.type(make(events))
            return repr((first, second, events, query(Item()), query(Child()),
                         query(4), query(True), query("yes"), query([1]), query(None),
                         integer(3), integer(True), integer(None)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_exact_proof_does_not_turn_mutable_storage_or_a_closure_into_an_int(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        def run(value: int | str) -> str:
            if type(value) is int:
                copied = value
                reader: Callable[[], str] = lambda: repr(value)
                lazy = (repr(value) for _ in range(1))
                value = True
                return repr((copied, reader(), next(lazy), type(value) is bool))
            return "other"
        def main() -> str:
            return run(7)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "type(1) is int", "type(True) is not int", "str is type('x')", "float is type(1.5)",
])
def test_exact_literal_builtin_identity(expression):
    result = LLVM().assert_matches_python(f"def main() -> str:\n    return repr({expression})\n")
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "type(1) is type(2)", "type(value=1) is int", "type(*(1,)) is int",
    "type(1) is bad", "type(1) is list[int]",
    "type(1) == int", "type(1) is int is object", "type(1)",
])
def test_dynamic_or_parameterized_exact_type_targets_are_located_diagnostics(expression):
    with pytest.raises(CompilationError) as caught:
        transpile_llvm(f"def main() -> int:\n    bad = 1\n    return int({expression})\n", filename="exact-type.py")
    assert "exact-type.py" in str(caught.value)


def test_integer_abi_keeps_its_existing_boolean_conversion_boundary():
    result = LLVM().assert_matches_python('''
def query(value: int) -> bool: return type(value) is int
def main() -> str: return repr(query(3))
''')
    assert not result.native.stderr
    with pytest.raises(LLVMUnsupported, match="cannot convert i1 to i64"):
        transpile_llvm('''
def query(value: int) -> bool: return type(value) is int
def main() -> int: return int(query(True))
''')
    with pytest.raises(LLVMUnsupported, match="cannot convert i64 to double"):
        transpile_llvm('''
def query(value: float) -> bool: return type(value) is float
def main() -> int: return int(query(1))
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_exact_proof_created_inside_a_lambda_and_a_query_only_class(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        class Unused: pass
        def reader(value: object) -> Callable[[], int]:
            return lambda: value if type(value) is int else 0
        def query(value: object) -> bool:
            return type(value) is Unused
        def main() -> str:
            a, b = reader(7), reader(True)
            return repr((a(), b(), query(3)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_shadowed_type_constructor_keeps_ordinary_object_identity():
    result = LLVM().assert_matches_python('''
class type: pass
def main() -> str: return repr(type() is type())
''')
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_concrete_containers_optional_identity_and_negative_base_checks(optimize):
    result = LLVM().assert_matches_python('''
        class Base: pass
        class Child(Base): pass
        def optional(value: Base | None) -> bool:
            return type(value) is Child
        def negative(value: int | str) -> str:
            if type(value) is not int:
                return repr(value)
            return "integer"
        def main() -> str:
            values = [1]
            mapping = {1: 2}
            members = {1}
            fixed = (1, "two")
            return repr((type(values) is list, type(mapping) is dict,
                         type(members) is set, type(fixed) is tuple,
                         optional(Child()), optional(Base()), optional(None),
                         negative(True), negative(1), negative("text")))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_specializations_share_class_identity_not_subclass_identity(optimize):
    result = LLVM().assert_matches_python('''
        class Box[T]:
            def __init__(self, value: T): self.value = value
        class Child(Box[int]): pass
        def query(value: object) -> bool: return type(value) is Box
        def tagged(value: Box[int] | int) -> bool: return type(value) is Box
        def main() -> str:
            a, b, c = Box[int](1), Box[str]("two"), Child(3)
            return repr((type(a) is Box, type(b) is Box, type(c) is Box,
                         query(a), query(b), query(c), tagged(a), tagged(1)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_ordinary_inline_calls_in_identity_comparisons_keep_call_context():
    result = LLVM().assert_matches_python('''
        from typing import cast
        def main() -> str:
            items = [1]
            value: object = items
            return repr(cast(list[int], value) is items)
    ''')
    assert not result.native.stderr


@pytest.mark.parametrize("declaration,expression", [
    ("from pyjs import int8", "type(int8(2)) is int"),
    ("from pyjs.web.domx import div\nfrom pyjs.web.dom import Element", "type(div()) is Element"),
])
def test_exact_queries_reject_erased_model_identity(declaration, expression):
    with pytest.raises(CompilationError):
        transpile_llvm(f"{declaration}\ndef main() -> int:\n    return int({expression})\n")


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("formatting", ["repr", "str"])
@pytest.mark.parametrize("deferred", ["lambda", "generator"])
def test_deferred_exact_binding_retains_its_own_formatting_runtime(optimize, formatting, deferred):
    create = (f"reader: Callable[[], str] = lambda: {formatting}(value)" if deferred == "lambda"
              else f"reader = ({formatting}(value) for _ in range(1))")
    consume = "reader()" if deferred == "lambda" else "next(reader)"
    # No surrounding repr: that would independently select the runtime and
    # mask a missing dependency in the deferred function itself.
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        def query(value: int | str) -> str:
            if type(value) is int:
                {create}
                first = {consume}
                {create}
                value = True
                return first + ":" + {consume}
            return "other"
        def main() -> str: return query(7)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_exact_generic_checks_preserve_known_container_parameters(optimize):
    result = LLVM().assert_matches_python('''
        class Box[T]:
            def __init__(self, value: T): self.value = value
        def items(value: list[int] | str) -> int:
            if type(value) is list: return sum(value)
            return -1
        def mapping(value: dict[str, int] | str) -> int:
            if type(value) is dict: return value["a"]
            return -1
        def boxed(value: Box[int] | str) -> int:
            if type(value) is Box: return value.value
            return -1
        def main() -> str:
            return repr((items([1, 2]), items("x"), mapping({"a": 4}),
                         mapping("x"), boxed(Box[int](5)), boxed("x")))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_exact_proofs_are_invalidated_by_writes_at_loop_and_exception_entries(optimize):
    result = LLVM().assert_matches_python('''
        def handler(value: int | str) -> str:
            if type(value) is int:
                try:
                    value = True
                    raise ValueError("after")
                except ValueError:
                    return repr(value)
            return "other"
        def loop(value: int | str) -> str:
            out: list[str] = []
            if type(value) is int:
                for _ in range(3):
                    out.append(repr(value))
                    value = True
            return repr(out)
        def while_loop(value: int | str, other: int | str) -> str:
            out: list[str] = []
            if type(value) is int and isinstance(other, int):
                index = 0
                while index < 3:
                    out.append(repr(value))
                    value = other
                    index += 1
            return repr(out)
        def main() -> str:
            return handler(5) + ":" + loop(5) + ":" + while_loop(5, True)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_writes_discard_exact_identity_without_losing_integer_type_narrowing(optimize):
    result = LLVM().assert_matches_python('''
        def augmented(value: int | str) -> int:
            if type(value) is int:
                value += 1
                return value * 2
            return -1
        def conditional(value: int | str, flag: bool) -> int:
            if type(value) is int:
                if flag: value = 3
                return value + 1
            return -1
        def loop(value: int | str, count: int) -> int:
            total = 0
            if type(value) is int:
                for item in range(count):
                    total += value
                    value = item
                return total + value
            return -1
        def handler(value: int | str) -> int:
            if type(value) is int:
                try:
                    value = 7
                    raise ValueError("after")
                except ValueError:
                    return value + 1
            return -1
        def main() -> str:
            return repr((augmented(5), augmented("x"), conditional(5, True),
                         conditional(5, False), conditional("x", True),
                         loop(5, 3), loop(5, 0), loop("x", 3),
                         handler(5), handler("x")))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_for_iterable_keeps_entry_proof_and_while_test_can_establish_a_fresh_one(optimize):
    result = LLVM().assert_matches_python('''
        def count(value: int) -> int: return value
        def query(value: int | str) -> str:
            out: list[str] = []
            if type(value) is int:
                for _ in range(count(value)):
                    out.append(repr(value))
                    value = True
            return repr(out)
        def repeated(value: int | str) -> str:
            out: list[int] = []
            while type(value) is int:
                out.append(count(value))
                value = True
            return repr(out)
        def main() -> str: return query(2) + ":" + repeated(5)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_inferred_integer_bindings_drop_exact_proofs_after_loop_and_handler_writes(optimize):
    result = LLVM().assert_matches_python('''
        def loop(source: int | str, count: int) -> str:
            out: list[str] = []
            if isinstance(source, int):
                value = source
                if type(value) is int:
                    for _ in range(count):
                        out.append(repr(value))
                        value = True
                    out.append("after:" + repr(value))
            return repr(out)
        def handler(source: int | str) -> str:
            if isinstance(source, int):
                value = source
                if type(value) is int:
                    try:
                        value = True
                        raise ValueError("after")
                    except ValueError:
                        return repr(value)
            return "other"
        def fresh(source: int | str) -> str:
            out: list[str] = []
            if isinstance(source, int):
                value = source
                while type(value) is int:
                    out.append(repr(value))
                    value = True
            return repr(out)
        def main() -> str:
            return ":".join([loop(7, 3), loop(7, 0), loop(True, 3), loop("x", 3), handler(7),
                             handler(True), handler("x"), fresh(7)])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_terminal_loop_else_writes_preserve_body_proofs_but_nested_else_writes_do_not(optimize):
    result = LLVM().assert_matches_python('''
        def take(value: int) -> int: return value
        def for_loop(value: int | str, count: int, stop: bool) -> str:
            out: list[int] = []
            if type(value) is int:
                for _ in range(count):
                    out.append(take(value))
                    if stop: break
                else:
                    value = True
            return repr(out) + ":" + repr(value)
        def while_loop(value: int | str, count: int, stop: bool) -> str:
            out: list[int] = []
            if type(value) is int:
                while count:
                    out.append(take(value))
                    count -= 1
                    if stop: break
                else:
                    value = True
            return repr(out) + ":" + repr(value)
        def nested(value: int | str) -> str:
            out: list[str] = []
            if type(value) is int:
                for _ in range(2):
                    out.append(repr(value))
                    for item in range(0):
                        out.append(repr(item))
                    else:
                        value = True
            return repr(out)
        def main() -> str:
            return "|".join([for_loop(7, 2, False), for_loop(7, 0, False),
                             for_loop(7, 2, True), for_loop("x", 2, False),
                             while_loop(7, 2, False), while_loop(7, 0, False),
                             while_loop(7, 2, True), while_loop("x", 2, False),
                             nested(7)])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("outer_loop", ["for _ in range(count):", "for _ in [0, 1]:", "while count:"])
@pytest.mark.parametrize("read_in_else", [False, True])
def test_nested_else_continue_cannot_restore_exact_proof_at_exhaustion(
    optimize, outer_loop, read_in_else,
):
    source = '''
        def query(source: int | str, count: int) -> str:
            if isinstance(source, int):
                value = source
                if type(value) is int:
                    for _ in range(count):
                        count -= 1
                        for inner in range(0):
                            pass
                        else:
                            value = True
                            continue
                    return repr(value)
            return "other"
        def main() -> str:
            return ":".join([query(7, 2), query(7, 0), query(True, 2), query("x", 2)])
    '''.replace("for _ in range(count):", outer_loop)
    if read_in_else:
        source = source.replace("                    return repr(value)",
                                "                    else:\n                        return repr(value)")
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
