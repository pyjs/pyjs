import pytest

from pyjs.android.testing import application_context
from pyjs.java import i32

pytestmark = pytest.mark.pyjs_android_jvm


def test_preferences_clear_is_deferred_and_composes_with_puts() -> None:
    preferences = application_context().get_shared_preferences("preferences-clear", i32(0))
    assert preferences.edit().put_string("old", "old value").commit()
    editor = preferences.edit().clear()
    assert preferences.get_string("old", "missing") == "old value"
    assert editor.put_string("new", "new value").commit()
    assert preferences.get_string("old", "missing") == "missing"
    assert preferences.get_string("new", "missing") == "new value"
    assert preferences.edit().clear().commit()
    assert preferences.get_string("new", "missing") == "missing"
