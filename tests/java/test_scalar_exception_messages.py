import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python


@pytest.mark.parametrize("payload", [
    "0", "-42", "9223372036854775807", "(-9223372036854775807 - 1)",
    "True", "False", "int8(255)", "uint8(255)", "int16(65535)",
    "uint16(65535)", "int32(4294967295)", "uint32(4294967295)",
    "int64(9007199254740993)",
])
def test_integer_and_boolean_exception_messages(tmp_path, payload):
    assert_text_matches_python(f'''
from pyjs import int8, uint8, int16, uint16, int32, uint32, int64

def main() -> str:
    messages: list[str] = []
    try:
        raise ValueError({payload})
    except ValueError as error:
        messages.append(str(error))
        messages.append(error.__str__())
    try:
        raise KeyError({payload})
    except KeyError as missing:
        messages.append(str(missing))
    try:
        assert False, {payload}
    except AssertionError as assertion:
        messages.append(str(assertion))
    return "|".join(messages)
''', tmp_path)


def test_scalar_message_evaluates_once_and_preserves_failure_cleanup(tmp_path):
    assert_text_matches_python('''
def revision(events: list[str], fail: bool) -> int:
    events.append("revision")
    if fail:
        raise RuntimeError("unavailable")
    return 42

def main() -> str:
    events: list[str] = []
    assert True, revision(events, True)
    for fail in [False, True]:
        try:
            try:
                raise ValueError(revision(events, fail))
            finally:
                events.append("cleanup")
        except ValueError as invalid:
            events.append(str(invalid))
        except RuntimeError as unavailable:
            events.append(str(unavailable))
    return "|".join(events)
''', tmp_path)


def test_scalar_string_conversions_share_python_spelling(tmp_path):
    assert_text_matches_python('''
def main() -> str:
    text = "plain"
    number = -42
    flag = False
    return (str(text) + ":" + str(number) + ":" + str(flag) + ":"
            + number.__str__() + ":" + flag.__str__() + ":"
            + f"{text}:{number}:{flag}")
''', tmp_path)


@pytest.mark.parametrize("payload", ["1.25", "None", "[1, 2]"])
@pytest.mark.parametrize("statement", ["raise ValueError(PAYLOAD)", "assert False, PAYLOAD"])
def test_unsupported_payload_has_located_diagnostic(payload, statement):
    source = "def main() -> int:\n    " + statement.replace("PAYLOAD", payload) + "\n    return 0\n"
    with pytest.raises(JVMUnsupported, match=(
        r"JVM exception messages require str, int, or bool at line 2"
    )):
        transpile_jvm(source)


@pytest.mark.parametrize("expression", ["str(value)", "value.__str__()", 'f"{value}"'])
def test_unsupported_scalar_conversion_has_located_diagnostic(expression):
    source = f"def main() -> str:\n    value = 1.25\n    return {expression}\n"
    with pytest.raises(JVMUnsupported, match=(
        r"JVM string conversion requires str, int, or bool at line 3"
    )):
        transpile_jvm(source)
