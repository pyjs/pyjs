import subprocess

import pytest

from pyjs.java import read_jvm_class, transpile_jvm
from tests.java.test_exceptions import assert_matches_python, run_jvm
from tests.java.test_jvm import java


def test_nullable_boolean_uses_reference_storage_without_changing_bool_abi():
    compilation = transpile_jvm('''
        class Decision:
            def __init__(self, value: bool | None): self.value = value
            def get(self) -> bool | None: return self.value
        def forward(value: bool | None) -> bool | None: return value
        def ordinary(value: bool) -> bool: return value
        def main() -> int:
            assert ordinary(True)
            return 1 if forward(Decision(None).get()) else 0
    ''')
    program = read_jvm_class(compilation.classes["PyjsProgram"])
    decision = read_jvm_class(compilation.classes["PyjsProgram$Decision"])
    assert [(field.name, field.descriptor) for field in decision.fields] == [
        ("value", "Ljava/lang/Boolean;"),
    ]
    assert [(method.name, method.descriptor) for method in decision.methods] == [
        ("<init>", "()V"),
        ("pyjs_init", "(Ljava/lang/Boolean;)V"),
        ("get", "()Ljava/lang/Boolean;"),
    ]
    assert sorted((method.name, method.descriptor) for method in program.methods) == [
        ("forward", "(Ljava/lang/Boolean;)Ljava/lang/Boolean;"),
        ("main", "([Ljava/lang/String;)V"),
        ("ordinary", "(Z)Z"),
        ("pyjs_main", "()J"),
    ]


@pytest.mark.parametrize("value", ["None", "False", "True"])
def test_nullable_boolean_arguments_returns_and_truth(tmp_path, value):
    assert_matches_python(f'''
        def forward(value: bool | None = None) -> bool | None:
            return value
        def inspect(value: bool | None) -> int:
            if value is None:
                return 1
            return 2 if value else 3
        def main() -> int:
            value = forward({value})
            assert forward() is None
            assert (1 if value else 0) == {int(value == "True")}
            if value is not None:
                assert not value == {value != "True"}
            return inspect(value)
    ''', tmp_path)


@pytest.mark.parametrize("value", ["None", "False", "True"])
def test_nullable_boolean_fields_and_reassignment(tmp_path, value):
    assert_matches_python(f'''
        class Decision:
            def __init__(self, value: bool | None):
                self.value = value
            def get(self) -> bool | None:
                return self.value
        def main() -> int:
            decision = Decision({value})
            assert (1 if decision.get() else 0) == {int(value == "True")}
            decision.value = True
            assert decision.get() is not None
            assert decision.get()
            decision.value = None
            assert decision.get() is None
            decision.value = False
            assert not decision.get()
            value: bool | None = None
            value = True
            if value is not None:
                assert value
            value = None
            assert value is None
            value = decision.get()
            return 1 if value else 2
    ''', tmp_path)


def test_nullable_boolean_truth_evaluates_call_once(tmp_path):
    assert_matches_python('''
        def consume(events: list[int], value: bool | None) -> bool | None:
            events.append(1)
            return value
        def main() -> int:
            events: list[int] = []
            if consume(events, True):
                events.append(2)
            if consume(events, False):
                return 9
            if consume(events, None):
                return 8
            return len(events)
    ''', tmp_path)


@pytest.mark.parametrize("value", ["None", "False", "True"])
def test_nullable_boolean_equality_and_identity(tmp_path, value):
    assert_matches_python(f'''
        def check(value: bool | None) -> int:
            score = 0
            if value == True:
                score += 1
            if False == value:
                score += 2
            if value != None:
                score += 4
            if value is True:
                score += 8
            if False is value:
                score += 16
            if value is None:
                score += 32
            return score
        def main() -> int:
            return check({value})
    ''', tmp_path)


def test_nullable_boolean_local_changes_across_control_flow(tmp_path):
    assert_matches_python('''
        def choose(clear: bool) -> bool | None:
            value: bool | None = True
            if clear:
                value = None
            return value
        def main() -> int:
            assert choose(True) is None
            assert choose(False) is True
            return 42
    ''', tmp_path)


def test_nullable_boolean_conditional_and_collection_storage(tmp_path):
    assert_matches_python('''
        def choose(value: bool) -> bool | None:
            return True if value else None
        def main() -> int:
            values: list[bool | None] = [None, False, True]
            values.append(choose(False))
            values.append(choose(True))
            score = 0
            for value in values:
                if value is None:
                    score += 1
                elif value:
                    score += 4
                else:
                    score += 2
            return score
    ''', tmp_path)


@pytest.mark.parametrize("value", ["None", "False", "True"])
@pytest.mark.parametrize(("operation", "index"), [
    ("values[0] = {value}", 0),
    ("values.insert(0, {value})", 0),
    ("values.append({value})", 1),
])
def test_nullable_boolean_list_mutation_boxes_values(tmp_path, operation, index, value):
    assert_matches_python(f'''
        def main() -> int:
            values: list[bool | None] = [None]
            {operation.format(value=value)}
            actual = values[{index}]
            if actual is None:
                return 1
            return 2 if actual else 3
    ''', tmp_path)


def test_nullable_boolean_dictionary_and_tuple_storage(tmp_path):
    assert_matches_python('''
        def pair(value: bool | None) -> tuple[bool | None, bool | None]:
            return value, True
        def main() -> int:
            values: dict[bool | None, bool | None] = {None: False}
            values[True] = None
            values[False] = True
            assert values[False] is True
            assert values[True] is None
            assert values.get(None) is False
            assert values.get(False, False) is True
            assert pair(None) is not None
            return 42
    ''', tmp_path)


def test_forwarded_native_constructor_boxes_boolean_reference(tmp_path):
    native = tmp_path / "BooleanBase.java"
    native.write_text('''
        public class BooleanBase {
            private final Boolean value;
            public BooleanBase(Boolean value) { this.value = value; }
            public boolean enabled() { return value.booleanValue(); }
        }
    ''')
    compiled = subprocess.run(
        [java(), "-Xmx128m", "-m", "jdk.compiler/com.sun.tools.javac.Main", str(native)],
        capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, compiled.stderr
    actual = run_jvm('''
        from typing import Annotated
        from pyjs import jvm
        from pyjs.java.primitives import Reference
        BoxedBool = Annotated[bool, Reference("java/lang/Boolean")]
        @jvm.native("BooleanBase")
        class BooleanBase:
            def __init__(self, value: BoxedBool): ...
            def enabled(self) -> bool: ...
        class Decision(BooleanBase):
            def __init__(self, value: bool):
                super().__init__(value)
        def main() -> int:
            assert Decision(True).enabled()
            assert not Decision(False).enabled()
            return 42
    ''', tmp_path)
    assert actual.returncode == 42, actual.stderr
