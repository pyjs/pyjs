import pytest

from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


@pytest.mark.parametrize("kind", ["ValueError", "KeyError", "SyntaxError"])
@pytest.mark.parametrize("payload", ["", '"saved"', "42", "False"])
def test_owned_builtin_keeps_identity_across_returns_fields_and_raises(tmp_path, kind, payload):
    assert_text_matches_python(f'''
class Pending:
    def __init__(self, error: {kind}):
        self.error = error

def make_error() -> {kind}:
    return {kind}({payload})

def main() -> str:
    saved: {kind} = make_error()
    pending = Pending(saved)
    errors: list[{kind}] = [pending.error]
    messages: list[str] = []
    for attempt in range(2):
        try:
            raise errors[0]
        except {kind} as caught:
            assert caught is saved
            messages.append(str(caught))
    return "|".join(messages)
''', tmp_path)


def test_constructing_an_exception_does_not_raise_it(tmp_path):
    assert_text_matches_python('''
def message(events: list[str]) -> str:
    events.append("message")
    return "saved"

def main() -> str:
    events: list[str] = []
    saved = ValueError(message(events))
    events.append("constructed")
    try:
        raise saved
    except ValueError as error:
        events.append(str(error))
    return "|".join(events)
''', tmp_path)


@pytest.mark.parametrize("kind", ["ValueError", "KeyError", "SyntaxError"])
def test_nullable_string_payload_distinguishes_none_from_omission(tmp_path, kind):
    assert_text_matches_python(f'''
def message(present: bool) -> str | None:
    return "text" if present else None

def main() -> str:
    messages: list[str] = []
    for present in [False, True]:
        try:
            raise {kind}(message(present))
        except {kind} as error:
            messages.append(str(error))
    return "|".join(messages)
''', tmp_path)


@pytest.mark.parametrize(("annotation", "argument", "check"), [
    ("list[int]", "[40, 2]", "failure.value[0] + failure.value[1] == 42"),
    ("Record", "Record(42)", "failure.value.code == 42"),
    ("float", "1.5", "failure.value == 1.5"),
])
def test_existing_field_only_exception_accepts_rich_payloads(tmp_path, annotation, argument, check):
    # Becoming throwable must not restrict previously valid field-only uses.
    assert_matches_python(f'''
class Record:
    def __init__(self, code: int):
        self.code = code

class Failure(Exception):
    def __init__(self, value: {annotation}):
        self.value = value

def main() -> int:
    failure = Failure({argument})
    return 42 if {check} else 1
''', tmp_path)


def test_existing_exception_explicit_string_override_is_preserved(tmp_path):
    assert_text_matches_python('''
class Failure(Exception):
    def __init__(self, code: int):
        self.code = code

    def __str__(self) -> str:
        return "code:" + str(self.code)

def main() -> str:
    return Failure(42).__str__()
''', tmp_path)


def test_existing_native_exception_override_keeps_java_dispatch(tmp_path):
    assert_text_matches_python('''
from pyjs import jvm

@jvm.native("java/lang/RuntimeException")
class NativeFailure(Exception):
    def __init__(self):
        pass

    def getMessage(self) -> str:
        return "native"

class Failure(NativeFailure):
    def getMessage(self) -> str:
        return "custom"

def message(failure: NativeFailure) -> str:
    return failure.getMessage()

def main() -> str:
    return message(Failure())
''', tmp_path)


@pytest.mark.parametrize("expression", ['NativeFailure("native")', "make_error()"])
def test_owned_native_exception_requires_an_explicit_constructor(tmp_path, expression):
    assert_text_matches_python(f'''
from pyjs import jvm

@jvm.native("java/lang/IllegalArgumentException")
class NativeFailure(Exception):
    def __init__(self, message: str):
        super().__init__(message)

def make_error() -> NativeFailure:
    return NativeFailure("native")

def main() -> str:
    try:
        raise {expression}
    except NativeFailure as error:
        return str(error)
    return "unhandled"
''', tmp_path)
