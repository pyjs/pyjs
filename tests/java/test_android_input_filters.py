import pytest

from pyjs.android import InputFilter, Runnable
from pyjs.android.controls import EditText
from pyjs.android.testing import application_context, run_on_main
from pyjs.android.text import LengthFilter
from pyjs.java import JVMArray

pytestmark = pytest.mark.pyjs_android_jvm


class LimitText(Runnable):
    def run(self) -> None:
        field = EditText(application_context())
        filters = JVMArray[InputFilter](1)
        limit = LengthFilter(3)
        assert limit.getMax() == 3
        filters[0] = limit
        field.setFilters(filters)
        assert len(field.getFilters()) == 1
        restored = field.getFilters()[0]
        assert isinstance(restored, LengthFilter)
        assert restored.getMax() == 3
        field.setText("A😀B")
        assert field.get_text().to_string() == "A😀"
        field.setText("AB😀")
        assert field.get_text().to_string() == "AB"
        field.get_text().replace(0, 1, "😀")
        assert field.get_text().to_string() == "😀B"
        field.get_text().replace(0, 2, "")
        assert field.get_text().to_string() == "B"
        field.setFilters(JVMArray[InputFilter](0))
        field.setText("Unlimited 😀 text")
        assert field.get_text().to_string() == "Unlimited 😀 text"


class ReplaceFilter(Runnable):
    def run(self) -> None:
        field = EditText(application_context())
        field.setText("Existing text")
        filters = JVMArray[InputFilter](1)
        filters[0] = LengthFilter(0)
        field.setFilters(filters)
        assert field.get_text().to_string() == "Existing text"
        field.get_text().replace(0, field.get_text().length(), "New text")
        assert field.get_text().to_string() == ""
        filters[0] = LengthFilter(4)
        field.setFilters(filters)
        field.get_text().replace(0, 0, "Longer")
        assert field.get_text().to_string() == "Long"


def test_native_length_filter_handles_utf16_insert_replace_delete_and_removal():
    run_on_main(LimitText())


def test_replacing_filters_changes_future_edits_without_rewriting_existing_text():
    run_on_main(ReplaceFilter())
