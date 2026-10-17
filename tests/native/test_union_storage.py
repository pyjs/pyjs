import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("source", [
    pytest.param('''
        def main() -> str:
            value: float | str = 1
            return str(value)
    ''', id="local"),
    pytest.param('''
        def value() -> float | str:
            return 1
        def main() -> str:
            return str(value())
    ''', id="return"),
    pytest.param('''
        class Value:
            def __init__(self):
                self.value: float | str = 1
        def main() -> str:
            return str(Value().value)
    ''', id="field"),
    pytest.param('''
        def main() -> str:
            values: list[float | str] = [1, 'a']
            return str(values)
    ''', id="list-display"),
    pytest.param('''
        def main() -> str:
            values: list[float | str] = []
            values.append(1)
            return str(values)
    ''', id="list-append"),
    pytest.param('''
        def main() -> str:
            values: dict[str, float | str] = {'x': 1}
            return str(values)
    ''', id="dict-display"),
    pytest.param('''
        def main() -> str:
            values: dict[str, float | str] = {}
            values['x'] = 1
            return str(values)
    ''', id="dict-setitem"),
    pytest.param('''
        def main() -> str:
            values: dict[float | str, int] = {1.0: 2}
            return str(values[1])
    ''', id="dict-lookup"),
    pytest.param('''
        def main() -> str:
            values: set[float | str] = {1.0}
            return str(1 in values)
    ''', id="set-lookup"),
    pytest.param('''
        def value(item: tuple[float | str, int]) -> str:
            return str(item)
        def main() -> str:
            return value((1, 2))
    ''', id="tuple-slot"),
])
def test_tagged_storage_rejects_implicit_numeric_promotion_with_location(source):
    # These were accepted by typing but produced an unsupported runtime tag.
    # Diagnostics must retain location through FieldStore/CollectionNew lowering.
    with pytest.raises(LLVMUnsupported, match=r"union values require an explicit numeric conversion at line \d+"):
        transpile_llvm(source)


@pytest.mark.parametrize("operation", [
    "members.add(key)", "members.discard(key)", "members.remove(key)",
    "mapping[key] = 2", "mapping.pop(key)", "del mapping[key]",
    "members = {key}", "mapping = {key: 2}", "mapping.update({key: 2})",
])
@pytest.mark.parametrize("key", ["1", "True"])
def test_tagged_key_mutation_checks_original_numeric_kind(operation, key):
    with pytest.raises(LLVMUnsupported, match="union values require an explicit numeric conversion"):
        transpile_llvm(f'''
            def main() -> str:
                key = {key}
                members: set[float | str] = {{1.0, 'a'}}
                mapping: dict[float | str, int] = {{1.0: 1}}
                {operation}
                return str((members, mapping))
        ''')


@pytest.mark.parametrize("padding", [0, 7])
def test_field_diagnostic_retains_exact_function_fragment_line(padding):
    # Native compilation diagnostics currently use function-fragment positions,
    # unlike runtime tracebacks. Check an exact position, not just any number.
    statements = "    pass\n" * padding
    source = ("class Value:\n"
              "    def __init__(self):\n"
              "        self.value: float | str = 'a'\n"
              "def main() -> str:\n"
              "    value = Value()\n" + statements +
              "    value.value = 1\n"
              "    return str(value.value)\n")
    with pytest.raises(LLVMUnsupported) as caught:
        transpile_llvm(source)
    assert str(caught.value) == f"LLVM union values require an explicit numeric conversion at line {3 + padding}"


@pytest.mark.parametrize("optimize", [0, 2])
def test_tagged_storage_explicit_conversions_and_comparison_only_controls(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def number() -> float | str:
            return float(1)

        class Value:
            def __init__(self):
                self.value: float | str = float(1)

        def main() -> str:
            gc_set_threshold(1)
            value: float | str = float(1)
            instance = Value()
            instance.value = 'updated'
            values: list[float | str] = [float(1), 'a']
            values.append(float(2))
            mapping: dict[str, float | str] = {'x': float(1)}
            mapping['y'] = float(2)
            keys: dict[float | str, int] = {1.0: 2}
            members: set[float | str] = {1.0}
            keys[float(2)] = 3
            members.add(float(2))
            members.discard(float(2))
            members.add(float(3))
            members.remove(float(3))
            removed = keys.pop(float(2))
            keys[float(3)] = 4
            del keys[float(3)]
            keys.update({float(1): 5})
            pair: tuple[float | str, int] = (float(1), 2)
            gc_collect()
            matches = (value == 1, number() == 1, 1 in values,
                       values.count(1), values.index(1), mapping == {'x': 1, 'y': 2},
                       keys[float(1)], float(1) in members,
                       [1] == [number()], pair == (1, 2))
            values.remove(1)
            return str((matches, values, instance.value, removed))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
