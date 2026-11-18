from pyjs.android import (
    Activity,
    Bundle,
    Button,
    EditorInfo,
    KeyEvent,
    LayoutParams,
    LinearLayout,
    LinearLayoutParams,
    OnClickListener,
    OnEditorActionListener,
    TextView,
    View,
)
from pyjs.android.controls import EditText, HorizontalScrollView
from pyjs.android.dialogs import AlertDialogBuilder, DialogClickListener, DialogInterface
from pyjs.java import i32


class DeferredRestoreActivity(Activity):
    pending: Bundle | None
    restore_calls: int

    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        self.pending = None
        self.restore_calls = 0
        if state is None:
            self.show_editor()
        else:
            loading = TextView(self)
            loading.setId(1010)
            loading.setText("Loading")
            self.setContentView(loading)

    def show_editor(self) -> None:
        field = EditText(self)
        field.setId(1011)
        field.setText("Initial")
        self.setContentView(field)

    def onRestoreInstanceState(self, state: Bundle) -> None:
        self.restore_calls += 1
        self.pending = state

    def complete_load(self) -> None:
        pending = self.pending
        assert pending is not None
        self.show_editor()
        super().onRestoreInstanceState(pending)
        self.pending = None


class HorizontalActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        for index in range(2):
            scroll = HorizontalScrollView(self)
            scroll.setId(i32(1001 + index))
            scroll.setLayoutParams(LinearLayoutParams(160, 60, 0.0))
            scroll.set_fill_viewport(True)
            child = TextView(self)
            child.setText("X")
            child.setMinimumWidth(i32(600 if index == 0 else 40))
            child.setLayoutParams(LayoutParams(LayoutParams.WRAP_CONTENT, 48))
            scroll.addView(child)
            root.addView(scroll)
        self.setContentView(root)


class ConfirmGreeting(DialogClickListener):
    def __init__(self, output: TextView) -> None:
        self.output = output

    def onClick(self, dialog: DialogInterface, which: i32) -> None:
        self.output.setText("Confirmed")


class ShowConfirmation(OnClickListener):
    def __init__(self, output: TextView) -> None:
        self.output = output

    def onClick(self, view: View) -> None:
        dialog = AlertDialogBuilder(view.getContext())
        dialog.setTitle("Confirm update?")
        dialog.setNegativeButton("Cancel", None)
        dialog.setPositiveButton("Confirm", ConfirmGreeting(self.output))
        dialog.show()


class InputAction(OnEditorActionListener):
    def __init__(self, output: TextView) -> None:
        self.output = output

    def onEditorAction(self, view: TextView, action: i32, event: KeyEvent | None) -> bool:
        self.output.setText(view.getText().to_string())
        return True


class GreetingClickListener(OnClickListener):
    def __init__(self, output: TextView) -> None:
        self.output = output

    def onClick(self, view: View) -> None:
        self.output.setText("Clicked from Python")


class GreetingActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        content = LinearLayout(self)
        content.setOrientation(LinearLayout.VERTICAL)
        content.setPadding(0, 200, 0, 0)
        greeting = TextView(self)
        greeting.setText("Hello from Python")
        output = TextView(self)
        output.setId(1001)
        output.setText("Waiting")
        if state is not None:
            output.setText(state.get_string("output") or "Waiting")
        self.output = output
        button = Button(self)
        button.setId(1002)
        button.setText("Update")
        button.setOnClickListener(GreetingClickListener(output))
        content.addView(greeting)
        content.addView(output)
        content.addView(button)
        confirm = Button(self)
        confirm.setText("Show confirmation")
        confirm.setOnClickListener(ShowConfirmation(output))
        content.addView(confirm)
        field = EditText(self)
        field.setId(i32(1004))
        field.setSingleLine(True)
        field.setImeOptions(EditorInfo.IME_ACTION_NEXT)
        field.setOnEditorActionListener(InputAction(output))
        content.addView(field)
        self.setContentView(content)

    def onSaveInstanceState(self, state: Bundle) -> None:
        state.put_string("output", self.output.getText().to_string())
        super().onSaveInstanceState(state)
