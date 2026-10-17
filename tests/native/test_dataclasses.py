from dataclasses import dataclass

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    DATACLASS_IDENTITY_CONTRACT,
    POSTPONED_DATACLASS_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
def test_dataclass_self_equality_skips_non_reflexive_fields(tmp_path, optimize):
    contract = DATACLASS_IDENTITY_CONTRACT
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_reference_and_init_disabled_scalar_factories(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass, field
        @dataclass
        class Record:
            label: str = field(default_factory=str)
            content: bytes = field(default_factory=bytes)
            members: set[int] = field(default_factory=set)
            frozen: frozenset[int] = field(default_factory=frozenset)
            count: int = field(default_factory=int, init=False)
        def main() -> str:
            first = Record()
            first.members.add(7)
            second = Record("next")
            return str((first.label, first.content, first.members, second.label, second.members, first.frozen, first.count))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_replacement_rejects_reached_polymorphic_records():
    with pytest.raises(LLVMUnsupported, match="non-polymorphic record"):
        transpile_llvm('''
            from dataclasses import dataclass, replace
            @dataclass
            class Base:
                x: int
            @dataclass
            class Child(Base):
                y: int = 9
            def clone(value: Base) -> Base:
                return replace(value, x=7)
            def main() -> int:
                return clone(Child(3)).x
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_replacement_preserves_explicit_keyword_order_for_authored_initializer(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass, replace
        events: list[str] = []
        @dataclass
        class Row:
            x: int
            y: int
            z: int
            def __init__(self, **values: int):
                for key in values:
                    events.append(key)
                self.x = values["x"]
                self.y = values["y"]
                self.z = values["z"]
        def main() -> str:
            row = Row(x=1, y=2, z=3)
            events.clear()
            result = replace(row, y=4, x=5)
            return str((result.x, result.y, result.z, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_generated_equality_defers_to_unrelated_and_subclass_overrides(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass
        from pyjs.native import gc_collect, gc_set_threshold
        events: list[str] = []
        @dataclass
        class Row:
            x: int
        @dataclass
        class Derived(Row):
            pass
        class Override(Row):
            def __eq__(self, other: object) -> bool:
                gc_collect()
                events.append("child")
                return True
        class Other:
            def __eq__(self, other: object) -> bool:
                gc_collect()
                events.append("other")
                return True
        def compare(left: Row, right: Row) -> bool:
            return left == right
        def main() -> str:
            gc_set_threshold(1)
            row = Row(1)
            other = Other()
            result = (row == other, other == row, row != other, other != row,
                      compare(row, Override(2)), compare(Override(2), row),
                      compare(row, Derived(1)), compare(Derived(1), row),
                      Row(1) == Row(1), Row(1) != Row(2))
            return str((result, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""

def test_postponed_dataclass_shared_contract(tmp_path):
    result = LLVM().assert_matches_python(POSTPONED_DATACLASS_CONTRACT, directory=tmp_path)
    assert result.native.returncode == 42
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_replace_reconstructs_after_changes_and_preserves_shared_fields(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass, field, replace
        from pyjs.native import gc_collect, gc_set_threshold

        events: list[str] = []

        @dataclass
        class Record:
            value: int
            values: list[int] = field(default_factory=list)
            doubled: int = field(init=False, default=0)

            def __post_init__(self):
                events.append("post")
                gc_collect()
                if self.value < 0:
                    raise ValueError("negative")
                self.doubled = self.value * 2

        def source(record: Record) -> Record:
            events.append("source")
            return record

        def change(record: Record, value: int) -> int:
            events.append("change")
            record.values = [8, 9]
            gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            original = Record(3, [1])
            updated = replace(source(original), value=change(original, 7))
            copied = replace(updated)
            try:
                replace(updated, value=-1)
            except ValueError:
                events.append("caught")
            final = replace(updated, value=10)
            gc_collect()
            return str((original.value, updated.value, copied.value, final.doubled,
                        updated.values, updated.values is original.values,
                        copied.values is updated.values, updated is copied, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_factories_are_fresh_and_inherited_post_init_runs_once_after_fields(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass, field
        from pyjs.native import gc_collect, gc_set_threshold

        events: list[str] = []

        def seeded() -> list[int]:
            events.append("factory")
            gc_collect()
            return [5]

        @dataclass
        class Base:
            values: list[int] = field(default_factory=list)
            counts: dict[str, int] = field(default_factory=dict)
            seeds: list[int] = field(default_factory=seeded)
            initialized: int = field(init=False, default=0)

            def __post_init__(self):
                events.append("post")
                self.initialized = len(self.seeds)

        @dataclass
        class Child(Base):
            label: str = "child"

        def main() -> str:
            gc_set_threshold(1)
            first = Child()
            second = Child(values=[7])
            first.values.append(2)
            first.counts["x"] = 3
            second.seeds.append(20)
            gc_collect()
            return str((first.values, second.values, first.counts, second.counts,
                        first.seeds, second.seeds, first.initialized, second.initialized,
                        first.values is second.values, first.seeds is second.seeds, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_factory_failure_skips_post_init_and_allows_gc_safe_retry(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass, field
        from pyjs.native import gc_collect, gc_set_threshold

        attempts: list[int] = [0]
        events: list[str] = []

        def seeded() -> list[int]:
            attempts[0] += 1
            events.append("factory")
            gc_collect()
            if attempts[0] % 2 == 1:
                raise ValueError("retry")
            return [attempts[0]]

        class Parent:
            def __post_init__(self):
                events.append("post")

        @dataclass
        class Record(Parent):
            first: list[int] = field(default_factory=list)
            seeded: list[int] = field(default_factory=seeded)

        def main() -> str:
            gc_set_threshold(1)
            results: list[int] = []
            for index in range(8):
                try:
                    Record()
                except ValueError:
                    gc_collect()
                current = Record()
                results.append(current.seeded[0])
                gc_collect()
            explicit = Record(seeded=[99])
            return str((results, explicit.seeded, attempts, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_replace_keyword_only_frozen_records_and_noninit_factories(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from __future__ import annotations
        from dataclasses import dataclass, field, replace
        from pyjs.native import gc_collect, gc_set_threshold

        calls: list[int] = []

        def fresh() -> list[int]:
            calls.append(len(calls))
            gc_collect()
            return [len(calls)]

        @dataclass(frozen=True, slots=True)
        class Item:
            value: int

        @dataclass(frozen=True, slots=True, kw_only=True)
        class Record:
            label: str
            items: tuple[Item, ...]
            fresh: list[int] = field(init=False, default_factory=fresh)

        def main() -> str:
            gc_set_threshold(1)
            source = Record(label="first", items=(Item(1), Item(2)))
            result = replace(source, label="second")
            result.fresh.append(7)
            gc_collect()
            return str((source.label, result.label, source.fresh, result.fresh,
                        source.items is result.items, result.items[1].value, calls))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_replace_borrowed_host_record_without_native_construction(tmp_path):
    @dataclass
    class Input:
        label: str
        values: list[int]
        scale: int
        total: int

        def __post_init__(self):
            self.total = len(self.values) * self.scale

    result = LLVM().assert_library_matches_python('''
        from dataclasses import dataclass, field, replace

        @dataclass
        class Record:
            label: str
            values: list[int]
            scale: int
            total: int = field(init=False, default=0)

            def __post_init__(self):
                self.total = len(self.values) * self.scale

        def render(value: Record) -> str:
            result = replace(value, label="native", scale=6)
            return str((result.label, result.values, result.scale, result.total))
    ''', Input("input", [4, 5, 6], 2, 6), directory=tmp_path, entry_point="render")
    assert result.matches
    result.library.close()


@pytest.mark.parametrize("changes", ["missing=1", "total=1", "value='bad'"])
def test_replace_validates_changes_before_native_emission(changes):
    with pytest.raises(CompilationError):
        transpile_llvm(f'''
            from dataclasses import dataclass, field, replace

            @dataclass
            class Record:
                value: int
                total: int = field(init=False, default=0)

            def main() -> int:
                result = replace(Record(3), {changes})
                return result.value
        ''')


def test_scalar_factory_has_an_explicit_native_boundary():
    with pytest.raises(LLVMUnsupported, match="default factories require reference-valued fields"):
        transpile_llvm('''
            from dataclasses import dataclass, field
            def one() -> int:
                return 1
            @dataclass
            class Record:
                value: int = field(default_factory=one)
            def main() -> int:
                return Record().value
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_replace_call_result_exposes_instance_fields_properties_and_methods(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass, replace
        @dataclass
        class Record:
            value: int
            def read(self) -> int: return self.value
            @property
            def doubled(self) -> int: return self.value * 2
        def main() -> str:
            item = Record(1)
            return str((replace(item, value=4).value, replace(item, value=5).read(),
                        replace(item, value=6).doubled, replace(replace(item, value=7), value=8).value,
                        item.value))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("options", ["frozen=True", "unsafe_hash=True"])
@pytest.mark.parametrize("base", ["", "(Base)"])
def test_generated_record_hash_is_not_silently_replaced_by_identity(options, base):
    # pytest includes source-location notes after the primary diagnostic.
    with pytest.raises(LLVMUnsupported, match=r"generated dataclass hashing is not implemented at line 2(?:\n|$)"):
        transpile_llvm(f'''
            from dataclasses import dataclass
            class Base:
                def __hash__(self) -> int:
                    return 7
            @dataclass({options})
            class Record{base}:
                value: int
            def main() -> int:
                return hash(Record(1))
        ''')


@pytest.mark.parametrize("padding", [0, 7])
@pytest.mark.parametrize("expression", ["hash(Record(1))", "len({Record(1): 1})"])
def test_generated_hash_diagnostic_tracks_the_consuming_function_line(padding, expression):
    # LLVMUnsupported uses function-relative AST coordinates. Moving the call
    # within its function must move the error, unlike adding module-level lines.
    source = ("from dataclasses import dataclass\n"
              "@dataclass(frozen=True)\nclass Record:\n    value: int\n"
              "def main() -> int:\n" + "    pass\n" * padding
              + f"    return {expression}\n")
    with pytest.raises(LLVMUnsupported, match=rf"generated dataclass hashing is not implemented at line {padding + 2}(?:\n|$)"):
        transpile_llvm("\n" * 20 + source)


@pytest.mark.parametrize("padding", [0, 5])
def test_generated_hash_diagnostic_uses_the_individual_method_fragment(padding):
    source = ("from dataclasses import dataclass\n"
              "@dataclass(frozen=True)\nclass Record:\n    value: int\n"
              "class Consumer:\n"
              "    def unrelated(self) -> int:\n" + "        pass\n" * 7
              + "        return 0\n"
              "    def consume(self) -> int:\n" + "        pass\n" * padding
              + "        return hash(Record(1))\n"
              "def main() -> int:\n    return Consumer().consume()\n")
    with pytest.raises(LLVMUnsupported, match=rf"generated dataclass hashing is not implemented at line {padding + 3}(?:\n|$)"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_record_keyed_containers_do_not_require_hash_implementation(tmp_path, optimize):
    # Retaining a potential key protocol does not mean these empty-container
    # operations call it. Frozen dataclass equality is independently supported.
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass
        @dataclass(frozen=True)
        class Record:
            value: int
        def count(values: dict[Record, int]) -> int:
            return len(values)
        def main() -> str:
            items: set[Record] = set()
            values: dict[Record, int] = {}
            return repr(([bool(items), len(items), Record(1) == Record(1), count(values)],
                         [key.value for key in values], [value for value in values.values()]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dataclass_hash_selection_keeps_authored_overrides_and_true_inheritance(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass
        from pyjs.native import gc_collect
        class Base:
            def __hash__(self) -> int:
                gc_collect()
                return 7
        @dataclass(eq=False)
        class Inherited(Base):
            value: int
        @dataclass(frozen=True)
        class Authored(Base):
            value: int
            def __hash__(self) -> int:
                gc_collect()
                return self.value
        class Child(Authored):
            pass
        def main() -> str:
            return repr([hash(Inherited(2)), hash(Authored(3)), hash(Child(5))])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
