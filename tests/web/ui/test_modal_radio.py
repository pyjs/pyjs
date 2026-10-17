import pytest

from pyjs.web.ui.alert_dialog import (
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
)
from pyjs.web.ui.radio_group import RadioGroup, RadioGroupItem
from pyjs.web.ui.sheet import (
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
)


@pytest.mark.pyjs_python
def test_alert_dialog_and_sheet_render_modal_semantics_on_the_server():
    alert = AlertDialog(
        AlertDialogTrigger("Delete"),
        AlertDialogContent(
            "Delete project",
            AlertDialogHeader(
                AlertDialogTitle("Are you sure?"),
                AlertDialogDescription("This action cannot be undone."),
            ),
            AlertDialogFooter(AlertDialogCancel("Cancel"), AlertDialogAction("Continue")),
        ),
    )
    sheet = Sheet(
        SheetTrigger("Open"),
        SheetContent(
            "Account settings",
            SheetHeader(
                SheetTitle("Account settings"),
                SheetDescription("Update your profile."),
            ),
            side="right",
        ),
    )

    assert alert.getAttribute("data-slot") == "alert-dialog"
    assert alert.content.dialog_element.getAttribute("role") == "alertdialog"
    assert alert.content.dialog_element.getAttribute("data-close-on-backdrop") == "false"
    assert sheet.getAttribute("data-slot") == "sheet"
    assert sheet.content.dialog_element.getAttribute("data-side") == "right"
    assert sheet.content.surface.getAttribute("class") == (
        "relative flex flex-col gap-4 p-6 data-[placement=left]:h-full "
        "data-[placement=right]:h-full"
    )


@pytest.mark.pyjs_python
def test_radio_group_uses_dom_state_and_validates_unique_values():
    group = RadioGroup(
        RadioGroupItem("comfortable", "Comfortable"),
        RadioGroupItem("compact", "Compact", checked=True),
        name="density",
    )

    assert group.current_value() == "compact"
    assert group.getAttribute("role") == "radiogroup"
    assert group.get_items()[0].control.getAttribute("name") == "density"

    with pytest.raises(ValueError, match="must be unique"):
        RadioGroup(RadioGroupItem("same", "First"), RadioGroupItem("same", "Second"))


@pytest.mark.pyjs_python
def test_radio_group_explicit_value_overrides_item_defaults_and_generates_a_shared_name():
    comfortable = RadioGroupItem("comfortable", "Comfortable")
    compact = RadioGroupItem("compact", "Compact", checked=True)
    group = RadioGroup(comfortable, compact, value="comfortable")

    assert group.current_value() == "comfortable"
    assert comfortable.is_checked()
    assert not compact.is_checked()
    assert comfortable.control.getAttribute("name") != ""
    assert comfortable.control.getAttribute("name") == compact.control.getAttribute("name")
