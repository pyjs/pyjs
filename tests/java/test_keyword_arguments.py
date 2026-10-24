import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from tests.backend_semantics import KEYWORD_ARGUMENT_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


def test_shared_keyword_argument_contract(tmp_path):
    assert_matches_python(KEYWORD_ARGUMENT_CONTRACT.source, tmp_path)


def test_keyword_only_calls_keep_defaults_evaluation_order_and_virtual_dispatch(tmp_path):
    assert_text_matches_python('''
from pyjs import int8, float32
class Base:
    def __init__(self, *, title: str, count: int = 1):
        self.title = title
        self.count = count
    def label(self, prefix: str = "", *, suffix: str, repeat: int = 1) -> str:
        return prefix + self.title + suffix * repeat
class Child(Base):
    def label(self, prefix: str = "", *, suffix: str, repeat: int = 1) -> str:
        return super().label(prefix, suffix=suffix, repeat=repeat) + "child"
def record(events: list[str], value: str) -> str:
    events.append(value)
    return value
def receiver(events: list[str]) -> Base:
    events.append("receiver")
    return Child(count=2, title="note")
def text(first: str, /, second: str = "default", *, third: str, fourth: str = "!") -> str:
    return first + second + third + fourth
def represented(*, number: int8, fraction: float32) -> float32:
    assert number == int8(127)
    return fraction
def main() -> str:
    events: list[str] = []
    value = text(record(events, "first"), third=record(events, "third"), second=record(events, "second"))
    assert value == "firstsecondthird!"
    assert "|".join(events) == "first|third|second"
    assert text("a", third="c") == "adefaultc!"
    events = []
    value = receiver(events).label(suffix=record(events, "."), prefix=record(events, ">"))
    assert value == ">note.child"
    assert "|".join(events) == "receiver|.|>"
    assert Base(title="default").count == 1
    assert represented(number=int8(127), fraction=float32(1.25)) == float32(1.25)
    assert represented(fraction=float32(2.5), number=int8(127)) == float32(2.5)
    return "matched"
''', tmp_path)


@pytest.mark.parametrize(("call", "message", "help_text"), [
    ("operation(1, 2)", "operation() received too many positional arguments",
     "Pass at most 1 positional arguments."),
    ("operation(1)", "operation() is missing required argument(s): 'second'",
     "Pass every required argument."),
    ("operation(1, second=2, unknown=3)", "operation() got an unexpected keyword argument 'unknown'",
     "Use a parameter name from the function signature."),
    ("operation(first=1, second=2)", "operation() parameter 'first' is positional-only",
     "Pass 'first' as a positional argument."),
])
def test_invalid_keyword_call_shapes_keep_analysis_diagnostics(call, message, help_text):
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(f'''def operation(first: int, /, *, second: int) -> int:
    return first + second
def main() -> int:
    return {call}
''', filename="keywords.py")
    assert caught.value.filename == "keywords.py"
    assert caught.value.lineno == 4
    assert caught.value.diagnostic.code == "PYJS1104"
    assert caught.value.diagnostic.message == message
    assert caught.value.diagnostic.help == (help_text,)


def test_keyword_argument_failure_stops_later_values(tmp_path):
    assert_text_matches_python('''
def record(events: list[str], value: str, fail: bool = False) -> str:
    events.append(value)
    if fail:
        raise ValueError(value)
    return value
def operation(*, first: str, second: str) -> str:
    return first + second
def main() -> str:
    events: list[str] = []
    try:
        operation(second=record(events, "second", fail=True), first=record(events, "first"))
    except ValueError as error:
        assert str(error) == "second"
    else:
        return "missing failure"
    return "|".join(events)
''', tmp_path)


def test_positional_only_methods_nullable_defaults_and_immediate_async_calls(tmp_path):
    assert_text_matches_python('''
from pyjs.java import run_sync
class Options:
    def __init__(self, name: str, /, *, enabled: bool = True, comment: str | None = None):
        self.name = name
        self.enabled = enabled
        self.comment = comment
    async def label(self, prefix: str, /, *, suffix: str = "!") -> str:
        return prefix + self.name + suffix
def main() -> str:
    first = Options("one")
    second = Options("two", comment="note", enabled=False)
    assert first.enabled and first.comment is None
    assert not second.enabled and second.comment == "note"
    return run_sync(second.label(">", suffix="."))
''', tmp_path)
