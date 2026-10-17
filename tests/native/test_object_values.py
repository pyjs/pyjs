from types import SimpleNamespace

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_checked_empty_tuple_cast_requires_exact_layout(tmp_path, optimize):
    # Native casts validate storage; unlike CPython's unchecked typing.cast,
    # nonempty tuple payloads must not acquire the empty tuple's static shape.
    # Even an empty variadic tuple has a different declared layout.
    result = LLVM().run_source('''
        from typing import cast
        from pyjs.native import gc_collect

        def variable(size: int) -> tuple[int, ...]:
            return tuple(range(size))

        def empty(value: object) -> str:
            item = cast(tuple[()], value)
            assert len(item) == 0 and item == ()
            return repr(item)

        def variable_cast(value: object) -> tuple[int, ...]:
            return cast(tuple[int, ...], value)

        def main() -> int:
            values: list[object] = [(1,), (1, "a"), [1], variable(0), variable(1)]
            for value in values:
                try:
                    empty(value)
                except TypeError:
                    pass
                else:
                    return 1
                gc_collect()
                assert empty(()) == "()"
            try:
                variable_cast(())
            except TypeError:
                pass
            else:
                return 2
            gc_collect()
            assert variable_cast(variable(0)) == variable(0)
            assert variable_cast(variable(2)) == variable(2)
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_identity_through_object_boundaries(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, number: int):
                self.number = number
        class Child(Base):
            pass
        class Empty:
            pass
        class Holder:
            def __init__(self, value: object):
                self.value = value

        def identity(value: object) -> object:
            gc_collect()
            return value

        def describe(value: object) -> str:
            if isinstance(value, Child):
                return "child:" + str(value.number)
            if isinstance(value, Base):
                return "base:" + str(value.number)
            if isinstance(value, Empty):
                return "empty"
            return "other:" + str(isinstance(value, object))

        def main() -> str:
            gc_set_threshold(1)
            child = Child(7)
            holder = Holder(identity(child))
            output = describe(holder.value) + str(holder.value is child)
            output += describe(identity(Base(3))) + describe(identity(Empty()))
            output += describe(identity(None)) + describe(identity("text"))
            return output + describe(identity([1, 2]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dataclass_equality_checks_exact_runtime_class(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass, field
        from pyjs.native import gc_collect

        @dataclass
        class Record:
            value: int
            label: str = field(compare=False)
        @dataclass
        class Child(Record):
            pass

        def compare(left: Record, right: Record) -> bool:
            gc_collect()
            return left == right

        def main() -> str:
            a = Record(2, "a")
            b = Record(2, "b")
            child = Child(2, "a")
            return str([compare(a, b), compare(a, Record(3, "a")),
                        compare(a, child), compare(child, a),
                        compare(child, Child(2, "c"))]) + repr(a)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_generated_dataclass_init_does_not_run_the_base_initializer(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass

        events: list[str] = []

        @dataclass
        class Base:
            value: int
            def __init__(self, value: int):
                events.append("base")
                self.value = value + 10

        @dataclass
        class Generated(Base):
            def __post_init__(self):
                events.append("post")
                self.value += 1

        @dataclass
        class Authored(Base):
            def __init__(self, value: int):
                super().__init__(value)
                events.append("authored")

        def main() -> str:
            generated = Generated(2)
            authored = Authored(3)
            return str(generated.value) + str(authored.value) + str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_mutated_object_field_does_not_reuse_stale_class_proof(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Box:
            def __init__(self):
                self.value = 7
        class Holder:
            def __init__(self, item: object):
                self.item = item

        def clear(holder: Holder):
            holder.item = None
            gc_collect()

        def main() -> str:
            holder = Holder(Box())
            if isinstance(holder.item, Box):
                clear(holder)
                try:
                    return str(holder.item.value)
                # CPython fails at attribute use; native checked typing fails
                # earlier, when loading the stale object-typed field.
                except Exception:
                    return "stale class proof rejected"
            return "missing branch"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_boxes_cross_calls_locals_fields_and_returns(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: object):
                self.value = value

        def identity(value: object) -> object:
            gc_collect()
            return value

        def returned(value: int) -> object:
            return value

        def describe(value: object) -> str:
            if isinstance(value, bool):
                return "bool:" + str(value)
            if isinstance(value, int):
                return "int:" + str(value + 1)
            if isinstance(value, float):
                return "float:" + str(value + 0.5)
            return "other"

        def pair(left: object, right: object, fail: bool) -> str:
            gc_collect()
            if fail:
                raise ValueError("retry")
            return describe(left) + describe(right)

        def main() -> str:
            gc_set_threshold(1)
            local: object = 7
            box = Box(41)
            output = describe(local) + describe(identity(True)) + describe(box.value)
            box.value = 1.5
            output += describe(box.value) + describe(returned(-9))
            output += describe(identity(int(int8(130)))) + describe(identity(float(float32(1.5))))
            output += str(identity(True) is identity(True)) + str(identity(False) is identity(False))
            output += str(identity(True) is identity(False))
            for index in range(12):
                try:
                    pair(index, index + 1, True)
                except ValueError:
                    pass
                output += pair(index, index + 1, False)
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_scalar_boxing_preserves_uninspected_host_record_layout(tmp_path):
    comparison = LLVM().assert_library_matches_python('''
        class Row:
            def __init__(self, value: int):
                self.value = value

        def ignore(value: object):
            pass

        def render(row: Row) -> str:
            ignore(42)
            return str(row.value)
    ''', SimpleNamespace(value=7), directory=tmp_path, entry_point="render")
    comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_casts_and_reboxing_keep_boolean_and_optional_kinds(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def identity(value: object) -> object:
            gc_collect()
            return value

        def describe(value: object) -> str:
            if isinstance(value, bool):
                return "bool:" + str(value)
            if isinstance(value, int):
                return "int:" + str(value)
            if isinstance(value, float):
                return "float:" + str(value)
            return "None"

        def optional(flag: bool) -> int | None:
            return int(int8(130)) if flag else None

        def union(flag: bool) -> int | str:
            return 42 if flag else "text"

        def main() -> str:
            gc_set_threshold(1)
            first = cast(int, cast(object, True))
            other = cast(float, cast(object, 3.5))
            return (describe(identity(first)) + str(other) +
                    describe(identity(optional(False))) + describe(identity(optional(True))) +
                    describe(identity(union(True))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("return_type, body", [
    ("str", "value: object = 42; first = int(cast(int, value)); other = cast(object, 3.5); return str((first, cast(float, other)))"),
    ("int", "return int(cast(int, cast(object, 42)))"),
])
def test_scalar_erasure_used_only_by_local_annotation_or_cast(tmp_path, optimize, return_type, body):
    # Keep these minimal: other object operations could hide a missing runtime
    # dependency when erasure appears only in a local declaration or nested cast.
    result = LLVM().assert_matches_python(f'''
        from typing import cast
        def main() -> {return_type}:
            {body}
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_scalar_erasure_preserves_reference_aliases_and_inferred_joins(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold
        def optional(flag: bool) -> int | None:
            return int(int8(130)) if flag else None
        def select(value: object, flag: bool):
            if flag:
                return value
            return int(int8(130))
        def conditional(value: object, flag: bool):
            return [1, 2] if flag else value
        def values(seed: object):
            yield seed
            yield "tail"
            yield int(int8(130))
            yield None
        def parent(seed: object):
            yield from values(seed)
            yield "after"
        def main() -> str:
            gc_set_threshold(1)
            stored: list[object] = []
            stored.append(int(int8(130)))
            stored.insert(0, float(float32(1.1)))
            stored[1] = int(int8(255))
            stored.append(optional(False))
            stored.append(optional(True))
            nested = [int8(130), int8(2)]
            stored.append(nested)
            nested[1] = int8(255)
            mapping: dict[str, object] = {}
            mapping["scalar"] = float(float32(2.2))
            mapping["nested"] = nested
            mapping["optional"] = optional(True)
            gc_collect()
            assert cast(list[int8], stored[4]) is nested
            assert cast(list[int8], mapping["nested"]) is nested
            assert nested[0] + int8(126) == 0
            joined: list[object] = []
            for flag in [True, False]:
                joined.append(select("head", flag))
                joined.append(conditional(7, flag))
                gc_collect()
            joined.extend(parent(42))
            gc_collect()
            return repr(stored) + repr(mapping) + repr(joined)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_receiver_boxes_fields_and_checks_narrowed_scalar_loads(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class First:
            def __init__(self):
                self.value: object = 4

        class Second:
            def __init__(self):
                self.padding = 42.0
                self.value: object = True

        def read(holder: First | Second) -> str:
            before = "missing"
            if isinstance(holder.value, int):
                before = str(holder.value)
            holder.value = 3.5
            gc_collect()
            if isinstance(holder.value, float):
                return before + str(holder.value + 0.5)
            return "wrong field"

        def main() -> str:
            gc_set_threshold(1)
            return read(First()) + read(Second())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
@pytest.mark.parametrize("kind", ["int", "str", "bytes"])
def test_box_allocation_failure_does_not_publish_partial_writes(tmp_path, optimize, managed, kind):
    from pyjs.native.llvm import transpile_llvm
    from tests.native.allocation_support import run_allocation_case

    def literal(number):
        return str(number) if kind == "int" else repr("x" * number if kind == "str" else b"x" * number)

    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        class Box:
            def __init__(self, value: object):
                self.value = value

        def read(value: object) -> int:
            if isinstance(value, {kind}):
                return {"int(value)" if kind == "int" else "len(value)"}
            return -1

        def identity(value: object) -> object:
            return value

        def returned(value: {kind}) -> object:
            return value

        def main() -> int:
            value: object = {literal(7)}
            box = Box(value)
            for mode in range(4):
                for repeat in range(8):
                    caught = False
                    arm(1)
                    try:
                        if mode == 0:
                            value = {literal(42)}
                        elif mode == 1:
                            value = identity({literal(42)})
                        elif mode == 2:
                            value = returned({literal(42)})
                        else:
                            box.value = {literal(42)}
                    except MemoryError:
                        caught = True
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    if not caught or read(value) != 7 or read(box.value) != 7:
                        return 1
            value = identity({literal(42)})
            box.value = returned({literal(43)})
            {'gc_collect()' if managed else 'pass'}
            return 0 if read(value) == 42 and read(box.value) == 43 else 2
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
