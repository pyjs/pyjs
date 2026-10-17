"""Native Android Calculator implementation."""

from pyjs.android import (
    Activity,
    Bundle,
    Button,
    Context,
    Gravity,
    LayoutParams,
    LinearLayout,
    LinearLayoutParams,
    OnClickListener,
    TextView,
    View,
    parse_color,
)
from pyjs.android.controls import ScrollView
from pyjs.java import f32, i32

from .model import Calculator


class CalculatorClickListener(OnClickListener):
    def __init__(
        self,
        calculator: AndroidCalculator,
        kind: str,
        value: str,
    ) -> None:
        self.calculator = calculator
        self.kind = kind
        self.value = value

    def onClick(self, view: View) -> None:
        self.calculator.press(self.kind, self.value)


class AndroidCalculator:
    def __init__(self, context: Context) -> None:
        self.context = context
        self.calculator = Calculator()

        self.display = TextView(context)
        self.display.setText(self.calculator.display_value)
        self.display.setTextSize(f32(40.0))
        self.display.setGravity(Gravity.END)
        self.display.setPadding(i32(24), i32(32), i32(24), i32(32))
        self.display.setBackgroundColor(parse_color("#020617"))

    def press(self, kind: str, value: str) -> None:
        self.calculator.press(kind, value)
        self.display.setText(self.calculator.display_value)

    def key(self, label: str, value: str, kind: str) -> Button:
        key = Button(self.context)
        key.setText(label)
        key.setTextSize(f32(22.0))
        key.setContentDescription(label)
        key.setPadding(i32(12), i32(16), i32(12), i32(16))
        key.setOnClickListener(CalculatorClickListener(self, kind, value))
        return key

    def page(self) -> ScrollView:
        root = LinearLayout(self.context)
        root.setOrientation(LinearLayout.VERTICAL)
        root.setGravity(Gravity.CENTER)
        root.setPadding(i32(20), i32(20), i32(20), i32(20))
        root.setBackgroundColor(parse_color("#0f172a"))
        root.setLayoutParams(
            LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT)
        )

        title = TextView(self.context)
        title.setText("PyJS Calculator")
        title.setTextSize(f32(24.0))
        title.setGravity(Gravity.CENTER_HORIZONTAL)
        root.addView(title)
        root.addView(self.display)

        keypad = LinearLayout(self.context)
        keypad.setOrientation(LinearLayout.VERTICAL)
        keypad.setLayoutParams(
            LinearLayoutParams(
                LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT, f32(0.0)
            )
        )
        labels = [
            ("AC", "clear", "action"),
            ("±", "sign", "action"),
            ("%", "percent", "action"),
            ("÷", "/", "operator"),
            ("7", "7", "digit"),
            ("8", "8", "digit"),
            ("9", "9", "digit"),
            ("×", "*", "operator"),
            ("4", "4", "digit"),
            ("5", "5", "digit"),
            ("6", "6", "digit"),
            ("−", "-", "operator"),
            ("1", "1", "digit"),
            ("2", "2", "digit"),
            ("3", "3", "digit"),
            ("+", "+", "operator"),
            ("0", "0", "digit"),
            (".", ".", "decimal"),
            ("=", "=", "equals"),
        ]
        row = LinearLayout(self.context)
        index = 0
        for label, value, kind in labels:
            if index % 4 == 0:
                row = LinearLayout(self.context)
                row.setOrientation(LinearLayout.HORIZONTAL)
                row.setLayoutParams(
                    LinearLayoutParams(
                        LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT, f32(0.0)
                    )
                )
                keypad.addView(row)
            key = self.key(label, value, kind)
            key.setId(i32(100 + index))
            key.setLayoutParams(
                LinearLayoutParams(i32(0), LayoutParams.WRAP_CONTENT, f32(1.0))
            )
            row.addView(key)
            index += 1
        root.addView(keypad)
        scroll = ScrollView(self.context)
        scroll.setFitsSystemWindows(True)
        scroll.set_fill_viewport(True)
        scroll.addView(root)
        return scroll


class CalculatorActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        self.setTitle("PyJS Calculator")
        self.view = AndroidCalculator(self)
        calculator = self.view.calculator
        if state is not None:
            calculator.display_value = state.get_string("display") or "0"
            calculator.stored_value = state.get_double("stored", 0.0)
            calculator.pending_operator = state.get_string("operator") or ""
            calculator.replace_display = state.get_boolean("replace", True)
            calculator.error = state.get_boolean("error", False)
        self.view.display.setText(calculator.display_value)
        self.setContentView(self.view.page())

    def onSaveInstanceState(self, state: Bundle) -> None:
        calculator = self.view.calculator
        state.put_string("display", calculator.display_value)
        state.put_double("stored", calculator.stored_value)
        state.put_string("operator", calculator.pending_operator)
        state.put_boolean("replace", calculator.replace_display)
        state.put_boolean("error", calculator.error)
        super().onSaveInstanceState(state)


def main() -> int:
    activity = CalculatorActivity()
    activity.onCreate(Bundle())
    return 0
