from pyjs.android import (
    Activity,
    Bundle,
    LinearLayout,
    OnClickListener,
    TextView,
    View,
    dp,
)
from pyjs.android.controls import EditText
from pyjs.android.insets import get_insets_controller, ime, root_window_insets
from pyjs.java import i32


class KeyboardAction(OnClickListener):
    def __init__(self, activity: Activity, field: EditText, status: TextView, action: str):
        self.activity = activity
        self.field = field
        self.status = status
        self.action = action

    def onClick(self, view: View) -> None:
        controller = get_insets_controller(self.activity.get_window(), self.field)
        if self.action == "Show":
            self.field.requestFocus()
            controller.show(ime())
        elif self.action == "Hide":
            controller.hide(ime())
        else:
            insets = root_window_insets(self.field)
            self.status.setText("Detached" if insets is None else (
                "Visible" if insets.is_visible(ime()) else "Hidden"))


class KeyboardActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        root.setFitsSystemWindows(True)
        root.setFocusableInTouchMode(True)
        root.setPadding(0, dp(self, 72), 0, 0)
        root.requestFocus()
        field = EditText(self)
        field.setId(i32(1001))
        field.setContentDescription("Editor")
        field.setText("Typed text")
        root.addView(field)
        status = TextView(self)
        status.setId(i32(1005))
        status.setContentDescription("Keyboard visibility")
        labels = ["Show", "Hide", "Inspect"]
        for index in range(len(labels)):
            label = labels[index]
            button = TextView(self)
            button.setId(i32(1002 + index))
            button.setText(label)
            button.setContentDescription(label + " keyboard")
            button.setMinimumHeight(dp(self, 48))
            button.setOnClickListener(KeyboardAction(self, field, status, label))
            root.addView(button)
        root.addView(status)
        self.setContentView(root)


def main() -> int:
    activity = KeyboardActivity()
    activity.onCreate(None)
    return 0
