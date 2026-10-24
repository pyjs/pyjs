import pytest

from tests.java.test_context_managers import assert_text_matches_python


@pytest.mark.parametrize(("annotation", "value", "default"), [
    ("int", "41", "7"),
    ("float", "2.5", "7.0"),
    ("bool", "True", "False"),
    ("str", '"value"', '"fallback"'),
    ("int | None", "None", "7"),
    ("str | None", "None", '"fallback"'),
])
def test_pop_retains_present_values_and_distinguishes_missing_keys(tmp_path, annotation, value, default):
    assert_text_matches_python(f'''
def main() -> str:
    values: dict[str, {annotation}] = {{"first": {value}, "second": {value}}}
    assert values.pop("first") == {value}
    assert values.pop("second", {default}) == {value}
    assert values.pop("missing", {default}) == {default}
    result = "popped:"
    assert len(values) == 0
    try:
        values.pop("missing")
    except KeyError as error:
        result += str(error)
    return result
''', tmp_path)


def test_pop_evaluates_default_before_removal_and_invalidates_iterators(tmp_path):
    assert_text_matches_python('''
def key(events: list[str]) -> str:
    events.append("key")
    return "first"
def default(values: dict[str, int], events: list[str]) -> int:
    events.append("default:" + str(len(values)))
    return values.pop("first") + 1
def main() -> str:
    values = {"first": 3, "last": 7}
    events: list[str] = []
    result = values.pop(key(events), default(values, events))
    assert result == 4
    assert len(values) == 1
    values["extra"] = 9
    try:
        for item in values:
            values.pop(item)
    except RuntimeError:
        events.append("changed")
    else:
        events.append("missed")
    return ":".join(events)
''', tmp_path)
