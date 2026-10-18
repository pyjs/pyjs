import subprocess

from pyjs.java import read_jvm_class, transpile_jvm
from tests.backend_semantics import KEY_ERROR_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python
from tests.java.test_jvm import java


def test_shared_key_error_contract(tmp_path):
    assert_matches_python(KEY_ERROR_CONTRACT.source, tmp_path)


def test_key_error_quotes_dynamic_strings_and_distinguishes_empty_args(tmp_path):
    keys = [
        "", "plain", "a'b", 'a"b', 'a\'"b', "\\", "\t\n\r", "\0\x1b\x7f\x85",
        "\xa0\u0378\u200b\u2028\u2029\ue000\uffff", "café 中文 😀", "\U000e0001\U000f0000",
        "\ud800", "\udfff", "\U0001fae9\u1c89",  # Unicode 16, newer than JDK 21.
        "".join(chr(value) for value in range(256)),
    ]
    assert_text_matches_python(f'''
def main() -> str:
    messages: list[str] = []
    try:
        raise KeyError()
    except KeyError as empty:
        messages.append(str(empty))
    for key in {keys!r}:
        try:
            raise KeyError(key)
        except KeyError as error:
            messages.append(str(error))
    return "|".join(messages)
''', tmp_path)


def test_dictionary_lookup_raises_key_error_without_repeating_evaluation(tmp_path):
    assert_text_matches_python('''
def key(events: list[str]) -> str:
    events.append("key")
    return "missing's title"

def mapping(events: list[str]) -> dict[str, str | None]:
    events.append("map")
    return {"present": None}

def main() -> str:
    events: list[str] = []
    try:
        mapping(events)[key(events)]
    except KeyError as error:
        events.append(str(error))
    values = mapping(events)
    assert values["present"] is None
    assert values.get("missing") is None
    assert values.get("missing", "default") == "default"
    return "|".join(events)
''', tmp_path)


def test_identity_dictionary_keys_keep_working_and_missing_keys_are_catchable(tmp_path):
    assert_matches_python('''
class Key:
    pass

def main() -> int:
    key = Key()
    values: dict[Key, str] = {key: "present"}
    assert values[key] == "present"
    try:
        values[Key()]
    except KeyError:
        return 42
    return 1
''', tmp_path)


def test_nullable_string_dictionary_key_error(tmp_path):
    assert_text_matches_python('''
def missing() -> str | None:
    return None

def main() -> str:
    values: dict[str | None, str] = {"present": "value"}
    messages: list[str] = []
    try:
        values[missing()]
    except KeyError as error:
        messages.append(str(error))
    try:
        values[None]
    except KeyError as literal_error:
        messages.append(str(literal_error))
    present: dict[str | None, str] = {None: "present"}
    messages.append(present[None])
    return "|".join(messages)
''', tmp_path)


def test_nullable_boolean_key_lookup_keeps_boxing_and_present_null(tmp_path):
    assert_matches_python('''
def main() -> int:
    values: dict[bool | None, str | None] = {True: "yes", None: None}
    assert values[True] == "yes"
    assert values[None] is None
    try:
        values[False]
    except LookupError:
        return 42
    return 1
''', tmp_path)


def test_repr_helpers_are_demand_driven_and_emitted_once():
    plain = transpile_jvm('def main() -> int:\n    return 42\n')
    assert not any(method.name.startswith("pyjs_string_")
                   for method in read_jvm_class(plain.classes["PyjsProgram"]).methods)
    quoted = transpile_jvm('''
def main() -> int:
    try:
        raise KeyError("first")
    except KeyError:
        raise KeyError("second")
''')
    methods = read_jvm_class(quoted.classes["PyjsProgram"]).methods
    assert [method.name for method in methods if method.name.startswith("pyjs_string_")] == [
        "pyjs_string_printable", "pyjs_string_repr",
    ]


def test_key_error_helper_uses_the_requested_main_class(tmp_path):
    source = '''
def label(value: str) -> str:
    try:
        raise KeyError(value)
    except KeyError as error:
        return str(error)

def main() -> str:
    return label("missing")
'''
    transpile_jvm(source, class_name="Quoted").write(tmp_path)
    result = subprocess.run(
        [java(), "-Xmx128m", "-Xverify:all", "-cp", str(tmp_path), "Quoted"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "'missing'"


def test_lookup_error_suppression_preserves_key_error_type_and_message(tmp_path):
    assert_matches_python('''
class Scope:
    def __enter__(self) -> None:
        pass

    def __exit__(self, kind: type[BaseException] | None,
                 value: BaseException | None, trace: object) -> bool:
        assert kind is KeyError
        assert isinstance(value, LookupError)
        assert str(value) == "'missing'"
        assert trace is not None
        return True

def main() -> int:
    values: dict[str, str] = {}
    with Scope():
        values["missing"]
    return 42
''', tmp_path)
