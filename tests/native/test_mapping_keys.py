import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,statement", [
    ("dict[int, int]", "value.pop(1)"), ("dict[int, int]", "value.pop(1, 0)"),
    ("dict[int, int]", "del value[1]"), ("dict[int, int]", "value[1] = 2"),
    ("dict[int, int]", "value.popitem()"), ("dict[int, int]", "value.update(value)"),
    ("dict[int, int]", "value.setdefault(1, 0)"), ("dict[str, int]", "value.pop('a')"),
    ("dict[tuple[int, int], int]", "value.setdefault((1, 2), 0)"),
    ("dict[tuple[int, int], int]", "value.pop((1, 2))"),
    ("dict[tuple[int, int], int]", "del value[(1, 2)]"),
    ("set[tuple[int, int]]", "value.remove((1, 2))"),
    ("dict[bytes, int]", "value.pop(b'a')"), ("dict[bytes | None, int]", "del value[b'a']"),
    ("set[bytes]", "value.remove(b'a')"),
    ("dict[int, int]", "value.clear()"), ("set[int]", "value.clear()"), ("set[int]", "value.pop()"),
    ("set[int]", "value.remove(1)"), ("set[int]", "value.discard(1)"),
    ("set[int]", "value.add(1)"), ("set[int]", "value.update(value)"),
])
def test_mutation_without_any_mapping_construction(tmp_path, optimize, annotation, statement):
    # The missing-helper regression is in an emitted but unexecuted branch.
    # Constructing a mapping to enter it would conceal the dependency defect;
    # the populated-operation tests below separately exercise runtime behavior.
    result = LLVM().assert_matches_python(f'''
        def mutate(value: {annotation} | None) -> None:
            if value is not None:
                {statement}

        def main() -> int:
            mutate(None)
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,expression", [
    ("dict[str, int]", "'a' in value"), ("dict[str, int]", "value.get('a', 0)"),
    ("dict[str, int]", "value['a']"), ("dict[int, int]", "value.get(0, 1)"),
    ("dict[tuple[int, int], int]", "value.get((1, 2), 0)"),
    ("dict[tuple[int, int], int]", "value[(1, 2)]"),
    ("dict[bytes, int]", "value[b'a']"), ("dict[bytes | None, int]", "value[b'a']"),
    ("set[int]", "0 in value"), ("frozenset[int]", "0 in value"),
])
def test_lookup_without_any_mapping_construction(tmp_path, optimize, annotation, expression):
    result = LLVM().assert_matches_python(f'''
        def lookup(value: {annotation} | None) -> int:
            return int({expression}) if value is not None else 0

        def main() -> int:
            return lookup(None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["dict[Key, int]", "set[Key]", "frozenset[Key]"])
@pytest.mark.parametrize("expression", ["Key(1) in value", "Key(1) not in value", "Key(1) in value is not None"])
def test_membership_without_custom_key_construction(tmp_path, optimize, annotation, expression):
    check_mapping_operator_without_construction(tmp_path, optimize, annotation, expression)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["set[Key]", "frozenset[Key]"])
@pytest.mark.parametrize("expression", [
    "value == value", "value != value", "value < value", "value <= value",
    "value > value", "value >= value", "len(value | value)", "len(value & value)",
    "len(value - value)", "len(value ^ value)",
])
def test_set_operators_without_custom_key_construction(tmp_path, optimize, annotation, expression):
    check_mapping_operator_without_construction(tmp_path, optimize, annotation, expression)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("member", ["int", "Key", "tuple[Key, int]"])
@pytest.mark.parametrize("expression", ["value == value", "value != value"])
def test_union_set_equality_without_construction(tmp_path, optimize, member, expression):
    check_mapping_operator_without_construction(
        tmp_path, optimize, f"set[{member}] | frozenset[{member}]", expression,
    )


def check_mapping_operator_without_construction(tmp_path, optimize, annotation, expression):
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __init__(self, number: int):
                self.number = number

            def __hash__(self) -> int:
                return self.number

            def __eq__(self, other: "Key") -> bool:
                return self.number == other.number

        def lookup(value: {annotation} | None) -> int:
            return int({expression}) if value is not None else 0

        def main() -> int:
            return lookup(None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,key,missing", [
    ("tuple[int, int]", "(1, 2)", "(9, 9)"), ("Key", "Key(1)", "Key(9)"),
    ("frozenset[int]", "frozenset([1, 2])", "frozenset([9])"),
    ("bytes", "b'a'", "b'\\x00\\xff'"), ("bytes | None", "None", "b'\\xff'"),
])
def test_reference_key_errors_without_explicit_formatting(tmp_path, optimize, annotation, key, missing):
    # Explicit formatting or a native helper such as gc_collect would mask
    # missing output-runtime selection. Cover success and implicit error text.
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __init__(self, number: int):
                self.number = number

            def __hash__(self) -> int:
                return self.number

            def __eq__(self, other: "Key") -> bool:
                return self.number == other.number

            def __repr__(self) -> str:
                return "key"

        def main() -> int:
            key = {key}
            missing = {missing}
            values: dict[{annotation}, int] = {{key: 3}}
            members: set[{annotation}] = {{key}}
            total = values[key]
            try:
                values[missing]
            except KeyError:
                total += 1
            try:
                values.pop(missing)
            except KeyError:
                total += 2
            try:
                del values[missing]
            except KeyError:
                total += 4
            try:
                members.remove(missing)
            except KeyError:
                total += 8
            total += values.pop(key)
            members.remove(key)
            return 0 if total == 21 and len(values) == 0 and len(members) == 0 else 1
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,key,missing", [
    ("Key", "Key(1)", "Key(9)"),
    ("tuple[Key, int]", "(Key(1), 2)", "(Key(9), 2)"),
])
def test_subscript_only_custom_key_retains_representation(tmp_path, optimize, annotation, key, missing):
    # No pop/delete/remove or explicit repr may incidentally retain __repr__.
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __init__(self, number: int):
                self.number = number

            def __hash__(self) -> int:
                return self.number

            def __eq__(self, other: "Key") -> bool:
                return self.number == other.number

            def __repr__(self) -> str:
                return "key" + str(self.number)

        def main() -> int:
            values: dict[{annotation}, int] = {{{key}: 3}}
            try:
                values[{missing}]
            except KeyError:
                return 0 if values[{key}] == 3 else 1
            return 2
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,expression", [
    ("list[set[Key]]", "values[0]"),
    ("dict[int, frozenset[Key]]", "values[0]"),
    ("tuple[dict[Key, int], int]", "values[0]"),
    ("list[set[Key]]", "values.pop()"),
    ("list[set[Key]]", "values.__getitem__(0)"),
    ("list[set[Key]]", "forward(values[0])"),
    ("dict[int, frozenset[Key]]", "values.pop(0)"),
    ("dict[int, frozenset[Key]]", "values.__getitem__(0)"),
    ("dict[int, frozenset[Key]]", "values.get(0, values[1])"),
    ("dict[int, frozenset[Key]]", "values.setdefault(0, values[1])"),
    ("dict[int, frozenset[Key]]", "values.pop(0, values[1])"),
])
@pytest.mark.parametrize("method", ["__hash__", "__eq__", "__repr__"])
def test_retrieved_mapping_results_do_not_retain_key_methods(tmp_path, optimize, annotation, expression, method):
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __hash__(self) -> int:
                return {"len(str(type(self)))" if method == "__hash__" else "1"}

            def __eq__(self, other: "Key") -> bool:
                return {"type(self) is type(other)" if method == "__eq__" else "True"}

            def __repr__(self) -> str:
                return {"str(type(self))" if method == "__repr__" else "'key'"}

        def forward(value: set[Key]) -> set[Key]:
            return value

        def lookup(values: {annotation} | None) -> int:
            return len({expression}) if values is not None else 0

        def main() -> int:
            return lookup(None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "[value][0]", "(value, 1)[0]", "{0: value}[0]",
    "[value].__getitem__(0)", "{0: value}.pop(0)", "{0: value}.get(0, value)",
])
def test_mapping_results_do_not_retain_unrelated_key_representation(tmp_path, optimize, expression):
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __hash__(self) -> int:
                return 1

            def __eq__(self, other: "Key") -> bool:
                return True

            def __repr__(self) -> str:
                # Unsupported when reached, but no operation formats this key.
                return str(1j)

        def main() -> int:
            value: dict[Key, int] = {{Key(): 3}}
            return len({expression}) - 1
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,expression", [
    ("dict[Key, int]", "dict(pairs)"),
    ("set[Key]", "set(keys)"),
    ("frozenset[Key]", "frozenset(keys)"),
    ("dict[Key, int]", "dict.fromkeys(keys, 7)"),
])
def test_mapping_builders_retain_callbacks_without_key_instances(tmp_path, optimize, annotation, expression):
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __hash__(self) -> int:
                return 1

            def __eq__(self, other: "Key") -> bool:
                return True

        def main() -> int:
            keys: list[Key] = []
            pairs: list[tuple[Key, int]] = []
            values: {annotation} = {expression}
            return len(values)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, first, second", [
    ("bytes", 'b"a\\x00\\xff"', 'b"b"'),
    ("bytes | None", 'b"a\\x00\\xff"', "None"),
    ("str | None", '"a\\x00é😀"', "None"),
    ("int | None", "0", "None"),
    ("bool | None", "False", "None"),
    ("float", "-0.0", "2.5"),
    ("float | None", "-0.0", "None"),
])
def test_mapping_key_storage_and_mutations(tmp_path, optimize, annotation, first, second):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            first: {annotation} = {first}
            second: {annotation} = {second}
            values: dict[{annotation}, int] = {{}}
            values[first] = 1
            values[second] = 2
            values[first] = 3
            assert len(values) == 2
            assert values.get(first, -1) == 3
            assert values.setdefault(second, 9) == 2
            copied = values.copy()
            gc_collect()
            assert copied == values and copied is not values
            del values[first]
            assert first not in values and first in copied
            values.update(copied)
            assert values.pop(second) == 2
            assert second not in values
            assert values.pop(second, -1) == -1
            values.clear()
            assert len(values) == 0
            failures = ""
            for key in [first, second]:
                try:
                    values[key]
                except KeyError as error:
                    failures += str(error) + ";"
                try:
                    values.pop(key)
                except KeyError as error:
                    failures += str(error) + ";"
            members: set[{annotation}] = {{first, second, first}}
            other: set[{annotation}] = {{second}}
            assert len(members) == 2 and members > other
            assert len(members & other) == 1
            assert first in members - other
            members ^= other
            assert first in members and second not in members
            frozen = frozenset(copied)
            assert first in frozen and second in frozen
            return str((copied, members, len(frozen))) + failures
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_optional_keys_preserve_aliases_and_missing_key_repr(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect
        def main(values: dict[bytes | None, int], key: bytes | None) -> str:
            copied = values.copy()
            gc_collect()
            try:
                return str(copied[key])
            except KeyError as error:
                return str(error)
    ''', tmp_path, optimize=optimize)
    try:
        data = {None: 4, b'a\x00\xff': 7}
        assert library.render(data, None) == '4'
        assert library.render(data, b'a\x00\xff') == '7'
        assert library.render(data, b'absent\x00\xff') == repr(b'absent\x00\xff')
        assert library.render({}, None) == 'None'
        assert data == {None: 4, b'a\x00\xff': 7}
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_keys_hash_once_and_keep_original_key_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int, events: list[str]):
                self.value = value
                self.events = events
            def __hash__(self) -> int:
                self.events.append('h' + str(self.value))
                gc_collect()
                return 0
            def __eq__(self, other: 'Key') -> bool:
                self.events.append('e' + str(self.value) + ':' + str(other.value))
                gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            first = Key(1, events)
            same = Key(1, events)
            different = Key(2, events)
            values = {first: 10}
            assert first in values
            assert same in values
            assert different not in values
            values[same] = 20
            assert len(values) == 1
            assert next(iter(values)) is first
            return '|'.join(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
