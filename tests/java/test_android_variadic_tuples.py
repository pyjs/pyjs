import pytest

pytestmark = pytest.mark.pyjs_android_jvm


def words(empty: bool) -> tuple[str, ...]:
    if empty:
        return ()
    return ("first", "second", "third")


def test_reference_tuple_aliases_indexing_and_iteration() -> None:
    values = words(False)
    alias = values
    assert alias is values
    assert values[-1] == "third"
    assert values[True] == "second"
    result = ""
    for value in values:
        result += value
    assert result == "firstsecondthird"
    assert len(words(True)) == 0


def test_tuple_bounds_errors_preserve_the_active_handler() -> None:
    values = words(True)
    original = ValueError("outer")
    try:
        raise original
    except ValueError:
        try:
            value = values[-1]
            raise AssertionError(value)
        except IndexError as error:
            assert error.__context__ is original
            assert str(error) == "tuple index out of range"
