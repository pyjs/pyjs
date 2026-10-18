import pytest

from pyjs.java import read_jvm_class, transpile_jvm
from tests.java.test_exceptions import assert_matches_python


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
