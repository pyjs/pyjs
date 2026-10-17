from pyjs.android import (
    Activity,
    Bundle,
    Button,
    EditorInfo,
    KeyEvent,
    LinearLayout,
    OnClickListener,
    OnEditorActionListener,
    TextView,
    View,
)
from pyjs.android.controls import EditText
from pyjs.android.dialogs import AlertDialogBuilder, DialogClickListener, DialogInterface
from pyjs.java import i32


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
