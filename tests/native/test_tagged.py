import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import UNION_NONE_GUARD_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["str(value)", "repr(value)", "print(value)"])
@pytest.mark.parametrize("guard", [False, True])
def test_narrowed_integer_formatters_prepare_their_own_dependencies(optimize, expression, guard):
    # Separate compilations prevent repr/format from masking print or str's
    # missing runtime dependencies. Loop narrowing has no guard provenance.
    statement = f"{expression}; return ''" if expression == "print(value)" else f"return {expression}"
    source = f'''
        def show(value: int | str) -> str:
            if isinstance(value, int):
                {statement}
            return value
        def main() -> str:
            return show(True) + show(2)
    ''' if guard else f'''
        def main() -> str:
            value: int | str = 'old'
            for value in [1, 2]:
                pass
            {statement}
    '''
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_narrowed_integer_numeric_consumers_preserve_python_results(optimize):
    result = LLVM().assert_matches_python('''
        def consume(value: int | str) -> str:
            if isinstance(value, int):
                return str((1.5 + value, 1.0 == value, 1.5 > value,
                            value == True, True == value, 'a' * value,
                            [7, 8, 9][value], list(range(value)), 'abc'[:value],
                            round(value), round(1.234, value), divmod(value, 2)))
            return value
        def main() -> str:
            return consume(True) + consume(2) + consume(False)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "b'abc'[value]", "value in b'\\x01\\x02'", "bytes(value)",
    "'z'.rjust(value)", "'z'.center(value)", "'z'.zfill(value)",
    "'a\\tb'.expandtabs(value)", "pow(value, 2, 5)", "pow(2, value, 5)",
    "pow(2, 3, value)", "range(5)[value]", "value in range(5)",
    "range(5).index(value)", "range(5)[:value]", "range(5)[::value]",
    "int('10', value)", "list(enumerate([7], start=value))",
    "value in iter([0, 1, 2])", "value in [0, 1, 2]", "value in {0, 1, 2}",
    "[2].count(value)", "[1, 2].index(value)", "(0, 1, 2).index(1, value)",
    "()[::value]",
])
def test_narrowed_numeric_only_consumers_unbox_at_the_boundary(optimize, expression):
    # Each consumer compiles alone: runtime selection must not depend on a
    # different operation in the same function. False also exercises errors.
    result = LLVM().assert_matches_python(f'''
        def consume(value: int | str) -> str:
            if isinstance(value, int):
                try:
                    return str({expression})
                except ValueError:
                    return 'value-error'
                except IndexError:
                    return 'index-error'
            return value
        def main() -> str:
            return consume(True) + '/' + consume(False) + '/' + consume(2) + '/' + consume(-1) + '/' + consume(256)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["value / divisor", "value.__rtruediv__(divisor)"])
def test_bool_division_prepares_its_own_integer_runtime(optimize, expression):
    result = LLVM().assert_matches_python(f'''
        def divide(value: bool, divisor: int) -> str:
            try:
                return str({expression})
            except ZeroDivisionError:
                return 'zero'
        def main() -> str:
            return divide(True, 2) + '/' + divide(False, 2) + '/' + divide(True, 0)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_gc_threshold_accepts_a_narrowed_integer_without_changing_identity(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def configure(value: int | str) -> str:
            if isinstance(value, int):
                try:
                    gc_set_threshold(value)
                except ValueError as error:
                    return str(error)
                gc_collect()
                return str(value)
            return value
        def main() -> str:
            return '/'.join([configure(True), configure(False), configure(0),
                             configure(-1), configure(10)])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("statement", ["return str({2: 'two'}[value])", "raise ValueError(value)"])
def test_narrowed_numeric_error_messages_keep_boolean_identity(optimize, statement):
    result = LLVM().assert_matches_python(f'''
        def observe(value: int | str) -> str:
            if isinstance(value, int):
                try:
                    {statement}
                except KeyError as error:
                    return str(error)
                except ValueError as error:
                    return str(error)
            return value
        def main() -> str:
            return observe(True) + '/' + observe(False) + '/' + observe(2)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("statement", [
    "return values.pop(value, 'missing') + '/' + str(values)",
    "result = values.pop(value); return result + '/' + str(values)",
    "del values[value]; return str(values)",
    "items.remove(value); return str(sorted(items))",
    "items.discard(value); return str(sorted(items))",
])
def test_narrowed_integer_removal_preserves_key_errors_and_mutates(optimize, statement):
    result = LLVM().assert_matches_python(f'''
        def remove(value: int | str) -> str:
            if isinstance(value, int):
                values = {{1: 'one', 2: 'two'}}
                items = {{1, 2}}
                try:
                    {statement}
                except KeyError as error:
                    return 'missing:' + str(error)
            return value
        def main() -> str:
            return remove(True) + '/' + remove(False) + '/' + remove(2) + '/' + remove(3)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_int_narrowing_keeps_boolean_identity(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect

        class Box:
            def __init__(self, value: int | str):
                self.value = value
        class Other:
            def __init__(self, value: int | str):
                self.value = value
        class Property:
            def __init__(self, value: int | str):
                self._value = value
            @property
            def value(self) -> int | str:
                return self._value

        def describe(value: int | str) -> str:
            if isinstance(value, int):
                gc_collect()
                if isinstance(value, int):
                    print(value)
                return (str(value) + '/' + repr(value) + '/' + json.dumps(value)
                        + '/' + format(value, '') + '/' + str(isinstance(value, bool))
                        + '/' + str(value + 2) + '/' + str(-value) + '/' + str(int(value)))
            return value

        def field(box: Box | Other) -> str:
            if isinstance(box.value, int):
                print(box.value)
                return repr(box.value) + '/' + json.dumps(box.value)
            return box.value

        def compare(value: int | str, other: int | str) -> str:
            if isinstance(value, int):
                return str(value == other) + str(other == value) + str(value is True)
            return value

        def widen(value: int | str) -> int | str:
            if isinstance(value, int):
                return value
            return value

        def property_value(box: Property) -> str:
            if isinstance(box.value, int):
                return repr(box.value) + '/' + str(box.value + 2)
            return box.value

        def main() -> str:
            return '|'.join([describe(True), describe(1), describe(False), field(Box(True)),
                             field(Other(False)), compare(True, 1), compare(False, 1), repr(widen(True)),
                             property_value(Property(True)), property_value(Property(False))])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("statement, diagnostic", [
    ("number: int = value; return str(number)", "narrowed int may be bool"),
    ("return str(min(value, 5))", "narrowed int may be bool"),
    ("return str(max(value, value))", "narrowed int may be bool"),
    ("return str(value & value)", "mixed bool bitwise"),
    ("return str(True & value)", "mixed bool bitwise"),
    ("return str(False | value)", "mixed bool bitwise"),
    ("return str(True ^ value)", "mixed bool bitwise"),
    ("return str(value.__rand__(True))", "mixed bool bitwise"),
])
def test_narrowed_tagged_integers_require_explicit_unboxed_conversion(statement, diagnostic):
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm(f'''
            def describe(value: int | str) -> str:
                if isinstance(value, int):
                    {statement}
                return value
            def main() -> str:
                return describe(True)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_narrowed_integer_load_rechecks_union_fields_and_properties(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        class First:
            def __init__(self, value: int | str):
                self.value = value
        class Second:
            def __init__(self, value: int | str):
                self.value = value
        class Changing:
            def __init__(self):
                self.count = 0
            @property
            def value(self) -> int | str:
                self.count += 1
                return True if self.count == 1 else 'changed'

        def mutate(holder: First | Second) -> None:
            holder.value = 'changed'
        def field(holder: First | Second) -> int:
            if isinstance(holder.value, int):
                mutate(holder)
                return holder.value + 1
            return 0
        def prop(holder: Changing) -> int:
            if isinstance(holder.value, int):
                return holder.value + 1
            return 0
        def main() -> int:
            count = 0
            try:
                field(First(True))
            except TypeError:
                count += 1
            try:
                field(Second(False))
            except TypeError:
                count += 1
            try:
                prop(Changing())
            except TypeError:
                count += 1
            return count
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_not_uses_union_and_length_truth_protocols(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        class Sized:
            def __len__(self) -> int:
                return 0
        def tagged(value: int | str) -> bool:
            return not value
        def optional(value: str | None) -> int:
            if not value:
                return 1
            return 0
        def main() -> str:
            return str([tagged(0), tagged(1), tagged(''), tagged('yes'),
                        bool(optional(None)), bool(optional('')), bool(optional('yes')), not Sized(), not None])
    ''', directory=tmp_path, optimize=optimize)
    assert comparison.native.stderr == ""


def test_numeric_union_unary_operator_has_located_diagnostic():
    from pyjs.analysis.diagnostics import CompilationError
    with pytest.raises(CompilationError, match="requires narrowing int\\|float"):
        transpile_llvm('''
            def negate(value: int | float) -> int | float:
                return -value
            def main() -> int:
                negate(1)
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_truth_uses_runtime_protocol_precedence_through_bases_and_unions(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            pass
        class Falsy(Base):
            def __bool__(self) -> bool:
                gc_collect()
                return False
        class Sized:
            def __len__(self) -> int:
                return 0
        class Truthy(Sized):
            def __bool__(self) -> bool:
                gc_collect()
                return True
            def __len__(self) -> int:
                return missing_unreachable_length()
        class Negative(Sized):
            def __len__(self) -> int:
                return -1
        class Unrelated:
            def __bool__(self) -> bool:
                return missing_unreachable_function()

        def base(value: Base) -> bool:
            return bool(value)
        def sized(value: Sized) -> bool:
            return bool(value)
        def union(value: Base | Sized | str) -> bool:
            return bool(value)
        def conditional(value: Base | Sized | str) -> int:
            return 1 if value else 0
        def inherited(value: Truthy) -> bool:
            return bool(value)
        def main() -> str:
            gc_set_threshold(1)
            results = [base(Base()), base(Falsy()), sized(Sized()), sized(Truthy()),
                       union(Base()), union(Falsy()), union(Sized()), union(Truthy())]
            Unrelated()
            checks = [conditional(Base()), conditional(Falsy()), conditional(Sized()),
                      conditional(Truthy()), int(inherited(Truthy()))]
            try:
                union(Negative())
            except ValueError as error:
                return str(results) + str(checks) + str(error)
            return "missing negative length error"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_iteration_and_unpacking_keep_reference_types_for_union_stores(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, text: str):
                self.text = text

        def main() -> str:
            gc_set_threshold(1)
            value: int | str = 0
            for value in ["a" + str(1), "b" + str(2)]:
                gc_collect()
            first = str(value)
            value, number = ("hello" + str(3), 12)
            gc_collect()
            item: int | Item = 0
            for item in [Item("owned" + str(4))]:
                gc_collect()
            if isinstance(item, Item):
                return first + str((value, number)) + item.text
            return "missing item"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("annotation, expression", [("list[None]", "[None]"),
                                                    ("dict[str, None]", '{"a": None}')])
def test_none_only_storage_inside_tagged_unions(annotation, expression):
    LLVM().assert_matches_python(f'''
            def read(value: {annotation} | int) -> str:
                return repr(value)
            def main() -> str:
                return read({expression})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_union_root_candidates_are_not_dereferenced(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def inspect(value: int | float | str) -> str:
            keep = ["owned" + str(9)]
            gc_collect()
            return repr(value) + keep[0]

        def main() -> str:
            gc_set_threshold(1)
            values: list[int | float | str] = [0, 1, -1, 9223372036854775807,
                                              1.25, float("inf"), float("nan"), "text"]
            return "|".join([inspect(value) for value in values])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_none_returns_from_tagged_functions_are_valid_zero_tags(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def explicit(value: int) -> int | str | None:
            gc_collect()
            if value == 0:
                return None
            return "owned" + str(value)

        def bare(value: int) -> int | str | None:
            if value == 0:
                return
            return value

        def implicit(value: int) -> int | str | None:
            if value != 0:
                return "yes"

        def main() -> str:
            gc_set_threshold(1)
            return str([(explicit(value), bare(value), implicit(value)) for value in range(3)])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_local_tagged_field_keeps_its_managed_payload_alive(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Holder:
            def __init__(self, value: int | str):
                self.value = value

        def populate(holder: Holder) -> None:
            holder.value = str(12345)

        def main() -> str:
            holder = Holder(0)
            populate(holder)
            gc_collect()
            return str(holder.value)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("number", ["int", "float"])
def test_unboxed_union_numeric_identity_is_not_silently_false(number):
    # Reach the identity boundary without an earlier int-to-float call mismatch.
    with pytest.raises(LLVMUnsupported, match="numeric identity.*at line"):
        transpile_llvm(f'''
            def same(value: {number} | str) -> bool:
                return value is value
            def main() -> str:
                return str(same({number}(1)))
        ''')


def test_union_widening_does_not_reinterpret_container_storage():
    with pytest.raises(LLVMUnsupported, match="collection views require.*invariant.*at line"):
        transpile_llvm('''
            def source() -> list[bool]:
                return [True]
            def inspect(value: list[int] | str) -> str:
                return repr(value)
            def main() -> str:
                return inspect(source())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_widening_preserves_base_class_identity_without_virtual_methods(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
            from pyjs.native import gc_collect
            class Base:
                def __init__(self):
                    self.value = 1
            class Child(Base):
                pass
            class Sibling(Base):
                pass
            def widen(value: Base) -> Base | str:
                return value
            def inspect(value: Base) -> str:
                result = str((isinstance(value, Base), isinstance(value, Child), isinstance(value, Sibling)))
                wider = widen(value)
                gc_collect()
                return result + str((isinstance(wider, Base), isinstance(wider, Child), isinstance(wider, Sibling)))
            def main() -> str:
                return inspect(Base()) + inspect(Child()) + inspect(Sibling())
        ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("method", ["__bool__", "__len__"])
def test_static_truth_descriptors_are_not_silently_ignored(method):
    result_type, result = ("bool", "False") if method == "__bool__" else ("int", "0")
    with pytest.raises(LLVMUnsupported, match="truth conversion requires instance special methods.*at line"):
        transpile_llvm(f'''
            class Item:
                @staticmethod
                def {method}() -> {result_type}:
                    return {result}
            def main() -> int:
                return int(bool(Item()))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_methods_bind_selected_defaults_and_keep_detached_receivers(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class First:
            def __init__(self, label: str):
                self.label = label
            def read(self, value: int = 1, *, suffix: str = "a") -> str:
                gc_collect()
                return self.label + str(value) + suffix

        class Second:
            def __init__(self, label: str):
                self.padding = 10
                self.label = label
            def read(self, value: int = 2, *, suffix: str = "b") -> int:
                gc_collect()
                return len(self.label) + value + len(suffix)

        class Holder:
            def __init__(self, value: First | Second):
                self.value = value

        def replace(holder: Holder, fail: bool) -> int:
            holder.value = First("replacement")
            gc_collect()
            if fail:
                raise ValueError("argument failed")
            return 3

        def read(holder: Holder, fail: bool) -> str:
            first = str(holder.value.read())
            try:
                return first + str(holder.value.read(replace(holder, fail), suffix="!"))
            except ValueError:
                return first + "caught"

        def main() -> str:
            gc_set_threshold(1)
            output: list[str] = []
            for fail in [False, True]:
                output.append(read(Holder(First("first" + str(1))), fail))
                output.append(read(Holder(Second("second" + str(2))), fail))
            return str(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_fields_use_each_members_layout_and_storage(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class First:
            def __init__(self):
                self.value: str | int = 4
                self.label: str | None = None
                self.count = int8(127)

        class Second:
            def __init__(self):
                self.padding = 42.0
                self.count = int8(-128)
                self.value = "initial"
                self.label: str | None = "present"

        def read(value: First | Second) -> str:
            before = str((value.value, value.label, value.count))
            value.value = "changed" + str(42)
            value.label = None
            value.count += int8(1)
            gc_collect()
            absent = value.label
            return before + str((value.value, absent, value.count))

        def main() -> str:
            gc_set_threshold(1)
            return read(First()) + read(Second())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_union_none_guard_contract(optimize):
    comparison = LLVM().assert_matches_python(UNION_NONE_GUARD_CONTRACT.source,
                                              optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_temporaries_survive_mutation_and_generator_suspension(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, label: str):
                self.label = label
            def __repr__(self) -> str:
                gc_collect()
                return self.label

        def clear(values: list[Item | int]) -> int:
            values.clear()
            gc_collect()
            return 4

        def sequence() -> Iterator[int | str]:
            value: int | str = "retained" + str(42)
            yield value
            gc_collect()
            yield value
            value = 12
            yield value

        def main() -> str:
            gc_set_threshold(1)
            values: list[Item | int] = [Item("first" + str(1))]
            before = str((values[0], clear(values)))
            cursor = sequence()
            first = next(cursor)
            gc_collect()
            rest = list(cursor)
            return str((before, first, rest, isinstance(first, object), isinstance(rest, list)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_closure_cells_keep_rebound_references_after_factory_exit(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def make() -> list[Callable[[], str]]:
            value: str | int | None = 1
            callbacks: list[Callable[[], str]] = []
            for value in [None, 42, "retained" + str(7)]:
                callback: Callable[[], str] = lambda: repr(value)
                callbacks.append(callback)
                gc_collect()
            return callbacks

        def main() -> str:
            gc_set_threshold(1)
            callbacks = make()
            gc_collect()
            return callbacks[0]() + callbacks[1]() + callbacks[2]()
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_portable_numeric_values_keep_normalized_payloads(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs import int8, float32
        from pyjs.native import gc_collect

        def integers(value: int8 | str | None) -> str:
            gc_collect()
            if value is None:
                return "none"
            if isinstance(value, str):
                return value
            return str(value + int8(1))

        def main() -> str:
            values: list[int8 | str | None] = [int8(127), "text", None, int8(255)]
            floats: list[float32 | str] = [float32(16777217), "float"]
            output: list[str] = []
            for value in values:
                output.append(integers(value))
            gc_collect()
            return str((values, floats, output))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_scalars_storage_narrowing_and_representation(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int | str | None):
                self.value = value

        def describe(value: int | str | None) -> str:
            gc_collect()
            if value is None:
                return "absent"
            if isinstance(value, int):
                return str(value + 1)
            return value.upper()

        def main() -> str:
            gc_set_threshold(1)
            values: list[int | str | None] = [4, "snow 雪", None]
            output: list[str] = []
            for value in values:
                box = Box(value)
                gc_collect()
                output.append(describe(box.value))
                output.append(repr(value))
                output.append(str(bool(value)))
            return str(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_equality_and_reference_aliases(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def widen(value: list[str]) -> int | list[str]:
            return value

        def equal(a: int | float | str | None, b: int | float | str | None) -> bool:
            gc_collect()
            return a == b

        def main() -> str:
            original = ["kept"]
            mixed = widen(original)
            gc_collect()
            same = mixed is original
            if isinstance(mixed, list):
                mixed.append("changed")
            results: list[bool] = []
            values: list[int | float | str | None] = [None, True, 1, 1.0, "1", 2.5]
            for left in values:
                for right in values:
                    results.append(equal(left, right))
            return str((same, original, results))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_nullable_widening_json_and_boolean_selection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        def widen(value: str | None) -> str | int | None:
            return value

        def choose(value: str | int | None) -> str | int:
            return value or "fallback"

        def main() -> str:
            gc_set_threshold(1)
            values: dict[str, str | int | None] = {}
            values["none"] = widen(None)
            values["str"] = widen("snow 雪")
            values["int"] = 42
            gc_collect()
            text = json.dumps(values, ensure_ascii=False)
            choices: list[str | int] = [choose(None), choose(""), choose(0), choose(3)]
            gc_collect()
            return text + str(choices)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_virtual_formatting_truth_and_changed_fields(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, label: str):
                self.label = label
            def __repr__(self) -> str:
                gc_collect()
                return "Item:" + self.label
            def __bool__(self) -> bool:
                gc_collect()
                return len(self.label) > 0

        class Child(Item):
            def __repr__(self) -> str:
                return "Child:" + self.label
            def __bool__(self) -> bool:
                return False

        class Holder:
            def __init__(self, value: str | int):
                self.value = value

        def widen(value: Item) -> Item | str:
            return value

        def change(holder: Holder) -> None:
            holder.value = 42
            gc_collect()

        def inspect(holder: Holder) -> str:
            if isinstance(holder.value, str):
                change(holder)
                try:
                    return str(len(holder.value))
                except TypeError:
                    return "changed"
            return "not str"

        def main() -> str:
            gc_set_threshold(1)
            values: list[Item | str] = [widen(Item("")), widen(Item("yes")), widen(Child("é")), "text"]
            output: list[bool] = []
            for value in values:
                output.append(bool(value))
            gc_collect()
            return str((values, output, inspect(Holder("original"))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_truth_methods_bind_defaults_and_check_length(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Flag:
            def __bool__(self, *, answer: bool = True) -> bool:
                gc_collect()
                return answer
            @staticmethod
            def __len__() -> int:
                return 0

        class Length:
            def __init__(self, value: int):
                self.value = value
            def __len__(self, offset: int = 1) -> int:
                gc_collect()
                return self.value + offset

        class BooleanLength:
            def __len__(self) -> bool:
                return True

        def main() -> str:
            gc_set_threshold(1)
            values: list[Flag | Length | BooleanLength | str] = [Flag(), Length(-1), Length(-2), BooleanLength(), ""]
            result = ""
            for value in values:
                try:
                    result += str(bool(value))
                except ValueError:
                    result += "negative"
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_numeric_and_length_builtins_reuse_concrete_semantics(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def source(value: int | float | str | None, events: list[str]) -> int | float | str | None:
            events.append("source")
            gc_collect()
            return value

        def convert(value: int | float | str | None, events: list[str]) -> str:
            result = ""
            try:
                result += str(int(source(value, events)))
            except ValueError:
                result += "integer error"
            except TypeError as error:
                result += str(error)
            try:
                result += str(float(source(value, events)))
            except ValueError:
                result += "float error"
            except TypeError as error:
                result += str(error)
            return result

        def length(value: str | bytes | list[int] | dict[str, int] | tuple[int, int] | None) -> int:
            gc_collect()
            try:
                return len(value)
            except TypeError:
                return -1

        def optional(value: str | None) -> str:
            try:
                return str((int(value), float(value), len(value)))
            except TypeError as error:
                return str(error)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values: list[int | float | str | None] = [True, 12, -3.75, " １２ ", "bad", None]
            result = ""
            for value in values:
                result += convert(value, events)
            lengths: list[str | bytes | list[int] | dict[str, int] | tuple[int, int] | None] = [
                "snow 雪😀", b"bytes", [1, 2, 3], {"a": 1}, (7, 9), None]
            for value in lengths:
                result += str(length(value))
            return result + repr(events) + optional("31") + optional(None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("operation, annotation, result_type", [
    *(('len', item + ' | None', 'int') for item in
      ('str', 'bytes', 'list[int]', 'dict[str, int]', 'tuple[int, int]', 'set[str]')),
    ('int', 'int | None', 'int'), ('float', 'float | None', 'float'),
])
def test_absence_only_calls_still_emit_reachable_concrete_dependencies(operation, annotation, result_type):
    # No string/list literal or formatting call can accidentally supply the
    # runtime dependency. main's integer result is the process exit code.
    source = f'''
        def convert(value: {annotation}) -> {result_type}:
            return {operation}(value)
        def main() -> int:
            try:
                convert(None)
                return 0
            except TypeError:
                return 7
    '''
    result = LLVM().assert_matches_python(source, optimize=2, sanitizers=("address", "undefined"))
    assert result.native.returncode == 7 and result.native.stderr == ""


def test_union_constructors_preserve_explicit_portable_result_widths():
    result = LLVM().assert_matches_python('''
        from pyjs import int8, float32

        def convert(value: int | float) -> str:
            return str((int8(int(value)), float32(value)))
        def main() -> str:
            return convert(16777217) + convert(130.75)
    ''', optimize=2, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
@pytest.mark.parametrize("optimize", [0, 2])
def test_union_fstrings_and_custom_formatters_evaluate_once_and_keep_roots(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, text: str):
                self.text = text
            def __format__(self, spec: str) -> str:
                gc_collect()
                return spec + self.text

        class Other:
            def __format__(self, spec: str) -> str:
                return spec + "other"

        class Holder:
            def __init__(self, value: Item | Other):
                self.value = value

        def spec(holder: Holder, events: list[int]) -> str:
            holder.value = Other()
            events.append(1)
            gc_collect()
            return ":"

        def number(value: int | float) -> str:
            return f"{value:08.2f}"

        def main() -> str:
            gc_set_threshold(1)
            values: list[int | float | str | None] = [1, 2.5, "text", None]
            output = [f"{value}" for value in values]
            output.extend([number(3), number(1.25)])
            holder = Holder(Item("owned" + str(9)))
            events: list[int] = []
            output.append(format(holder.value, spec(holder, events)))
            output.append(format(holder.value, "!"))
            output.append(str(events))
            return "|".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
