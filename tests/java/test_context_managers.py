from textwrap import dedent, indent

import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import CONTEXT_MANAGER_CONTRACT
from tests.java.test_exceptions import assert_matches_python, run_jvm
from tests.semantics.helpers import run_python

MANAGER = '''
class Scope:
    def __init__(self, events: list[str], name: str, suppress: bool = False,
                 fail_enter: bool = False, fail_exit: bool = False):
        self.events = events
        self.name = name
        self.suppress = suppress
        self.fail_enter = fail_enter
        self.fail_exit = fail_exit

    def __enter__(self) -> str:
        self.events.append("enter:" + self.name)
        if self.fail_enter:
            raise ValueError("enter failed")
        return self.name

    def __exit__(self, kind: type[BaseException] | None,
                 value: BaseException | None, traceback: object) -> bool:
        state = "normal"
        if value is not None:
            assert kind is not None and traceback is not None
            state = str(value)
        else:
            assert kind is None and traceback is None
        self.events.append("exit:" + self.name + ":" + state)
        if self.fail_exit:
            raise RuntimeError("exit failed")
        return self.suppress
'''


def assert_text_matches_python(source, directory):
    expected = run_python(source + '\nprint(main(), end="")\n')
    assert expected.returncode == 0, expected.stderr
    actual = run_jvm(source, directory)
    assert actual.returncode == 0, actual.stderr
    assert actual.stdout == expected.stdout


def test_shared_context_manager_contract(tmp_path):
    assert_matches_python(CONTEXT_MANAGER_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("body", [
    '''
    with Scope(events, "outer"), Scope(events, "inner") as value:
        events.append(value)
    ''',
    '''
    try:
        with Scope(events, "outer"), Scope(events, "inner", False, True):
            events.append("unreachable")
    except ValueError:
        events.append("caught")
    ''',
    '''
    with Scope(events, "outer", True), Scope(events, "inner"):
        raise ValueError("body")
    events.append("continued")
    ''',
    '''
    try:
        with Scope(events, "outer"), Scope(events, "inner", False, False, True):
            raise ValueError("body")
    except RuntimeError:
        events.append("caught")
    ''',
    '''
    try:
        with Scope(events, "exit", False, False, True):
            events.append("body")
    except RuntimeError:
        events.append("caught")
    ''',
    '''
    for index in range(3):
        with Scope(events, str(index)):
            if index == 0:
                continue
            break
    ''',
    '''
    try:
        raise TypeError("outer")
    except TypeError:
        with Scope(events, "normal-in-handler"):
            events.append("body")
    ''',
], ids=["nested", "failed-enter", "suppression", "replacing-error",
        "failed-normal-exit", "loop-exits", "normal-with-active-exception"])
def test_context_cleanup_paths(tmp_path, body):
    source = MANAGER + '\ndef main() -> str:\n    events: list[str] = []\n'
    source += indent(dedent(body).strip(), "    ")
    source += '\n    return "|".join(events)\n'
    assert_text_matches_python(source, tmp_path)


@pytest.mark.parametrize(("result_type", "value", "check"), [
    ("int", "42", "value == 42"),
    ("float", "1.25", "value == 1.25"),
    ("str", '"saved"', 'value == "saved"'),
    ("list[int]", "[42]", "value[0] == 42"),
    ("None", "None", "value is None"),
])
def test_return_saved_across_nested_cleanup(tmp_path, result_type, value, check):
    source = MANAGER + f'''
def early(events: list[str]) -> {result_type}:
    with Scope(events, "outer"), Scope(events, "inner"):
        return {value}
    return {value}

def main() -> int:
    events: list[str] = []
    value = early(events)
    assert {check}
    assert "|".join(events) == "enter:outer|enter:inner|exit:inner:normal|exit:outer:normal"
    return 42
'''
    assert_matches_python(source, tmp_path)


def test_virtual_exit_and_concrete_exception_token(tmp_path):
    assert_matches_python('''
        class Scope:
            def __enter__(self) -> None:
                pass
            def __exit__(self, kind: object, value: object, traceback: object) -> int:
                return 0

        class Suppressor(Scope):
            def __exit__(self, kind: object, value: object, traceback: object) -> int:
                return 1 if kind is ValueError else 0

        def use(scope: Scope) -> int:
            with scope as value:
                assert value is None
                raise ValueError("suppressed")
            return 42

        def main() -> int:
            return use(Suppressor())
    ''', tmp_path)


def test_none_exit_propagates_and_normal_exit_ignores_truth(tmp_path):
    assert_matches_python('''
        class Scope:
            def __init__(self, events: list[int]):
                self.events = events
            def __enter__(self) -> None:
                pass
            def __exit__(self, kind: object, value: object, traceback: object) -> None:
                self.events.append(1)

        def main() -> int:
            events: list[int] = []
            with Scope(events):
                pass
            try:
                with Scope(events):
                    raise ValueError("body")
            except ValueError:
                return len(events)
            return 9
    ''', tmp_path)


def test_native_reader_closes_on_return_and_has_typed_failure(tmp_path):
    actual = run_jvm('''
        from pyjs import jvm
        from pyjs.java import i32

        @jvm.native("java/io/IOException")
        class IOException(Exception):
            def getMessage(self) -> str | None: ...

        @jvm.native("java/io/StringReader")
        class StringReader:
            def __init__(self, value: str): ...
            def read(self) -> i32: ...
            def close(self) -> None: ...

        class Reading:
            def __init__(self, reader: StringReader):
                self.reader = reader
            def __enter__(self) -> StringReader:
                return self.reader
            def __exit__(self, kind: object, value: object, traceback: object) -> None:
                self.reader.close()

        def first(reader: StringReader) -> int:
            with Reading(reader) as source:
                return source.read()

        def message(error: Exception) -> str:
            return str(error)

        def main() -> int:
            reader = StringReader("note")
            assert first(reader) == 110
            try:
                reader.read()
            except ValueError:
                return 1
            except IOException as error:
                assert len(str(error)) > 0
                assert isinstance(error, IOException)
                assert error.getMessage() == message(error)
                return 42
            return 2
    ''', tmp_path)
    assert actual.returncode == 42, actual.stderr


@pytest.mark.parametrize("caught", ["Exception", "(NumberFormatException, IOException)"])
def test_native_exception_narrowing_keeps_receiver_descriptor(tmp_path, caught):
    result = run_jvm(f'''
        from pyjs import jvm
        from pyjs.java import i32

        @jvm.native("java/io/IOException")
        class IOException(Exception):
            pass

        @jvm.native("java/lang/NumberFormatException")
        class NumberFormatException(Exception):
            def getMessage(self) -> str | None: ...

        @jvm.native("java/lang/Integer", name="parseInt")
        def parse(value: str) -> i32: ...

        def main() -> int:
            try:
                parse("invalid")
            except {caught} as error:
                assert len(str(error)) > 0
                if isinstance(error, NumberFormatException):
                    assert error.getMessage() is not None
                    try:
                        raise error
                    except NumberFormatException as saved:
                        return 42 if saved is error else 1
            return 2
    ''', tmp_path)
    assert result.returncode == 42, result.stderr


def test_as_target_failure_runs_exit(tmp_path):
    source = MANAGER + '''
def main() -> str:
    events: list[str] = []
    values = ["unchanged"]
    with Scope(events, "binding", True) as values[2]:
        events.append("unreachable")
    assert values[0] == "unchanged"
    return "|".join(events)
'''
    assert_text_matches_python(source, tmp_path)


def test_cleanup_exception_replaces_a_pending_return(tmp_path):
    source = MANAGER + '''
def early(events: list[str]) -> int:
    with Scope(events, "fail", False, False, True):
        return 42
    return 0
def main() -> str:
    events: list[str] = []
    try:
        early(events)
    except RuntimeError as error:
        events.append(str(error))
    return "|".join(events)
'''
    assert_text_matches_python(source, tmp_path)


@pytest.mark.parametrize("fail", [False, True])
def test_exit_truth_is_only_evaluated_for_exceptional_cleanup(tmp_path, fail):
    assert_matches_python(f'''
        class Verdict:
            def __bool__(self) -> bool:
                raise RuntimeError("truth failed")

        class Scope:
            def __enter__(self) -> None:
                pass
            def __exit__(self, kind: object, value: object, traceback: object) -> Verdict:
                return Verdict()

        def main() -> int:
            try:
                with Scope():
                    if {fail}:
                        raise ValueError("body")
            except RuntimeError as error:
                return 42 if str(error) == "truth failed" else 1
            return 12
    ''', tmp_path)


def test_void_call_is_evaluated_once_when_used_as_none(tmp_path):
    assert_matches_python('''
        def record(events: list[int]) -> None:
            events.append(1)
        def forward(events: list[int]) -> None:
            return record(events)
        def main() -> int:
            events: list[int] = []
            value = forward(events)
            assert value is None
            assert record(events) is None
            return len(events)
    ''', tmp_path)


def test_native_exception_construction_does_not_guess_java_overloads():
    with pytest.raises(JVMUnsupported, match="native exception construction requires an explicit"):
        transpile_jvm('''
            from pyjs import jvm
            @jvm.native("java/lang/AssertionError")
            class NativeAssertionError(BaseException):
                pass
            def main() -> int:
                raise NativeAssertionError("failed")
        ''')
