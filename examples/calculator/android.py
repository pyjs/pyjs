from pyjs import js
from pyjs.nativescript import (
    Application,
    Button,
    EventData,
    GridLayout,
    Label,
    Page,
    StackLayout,
)
from pyjs.tooling.nativescript import NativeScriptProject

from .calculator import calculate_result


@js
class CalculatorButtonListener:
    def __init__(self, calculator: AndroidCalculator, kind: str, value: str):
        self.calculator = calculator
        self.kind = kind
        self.value = value

    def handleEvent(self, event: EventData):
        self.calculator.press(self.kind, self.value)


@js
class AndroidCalculator:
    def __init__(self):
        self.display_value = "0"
        self.stored_value = 0.0
        self.pending_operator = ""
        self.replace_display = True
        self.error = False

        self.display = Label()
        self.display.id = "calculator-display"
        self.display.testID = "calculator-display"
        self.display.text = self.display_value
        self.display.className = (
            "mb-4 rounded-2xl bg-slate-950 p-5 text-right text-5xl "
            "font-bold text-white"
        )

    def update_display(self):
        self.display.text = self.display_value

    def clear(self):
        self.display_value = "0"
        self.stored_value = 0.0
        self.pending_operator = ""
        self.replace_display = True
        self.error = False
        self.update_display()

    def value(self) -> float:
        if self.error:
            return 0.0
        return float(self.display_value)

    def input_digit(self, digit: str):
        if self.error:
            self.clear()
        if self.replace_display or self.display_value == "0":
            self.display_value = digit
            self.replace_display = False
        else:
            self.display_value += digit
        self.update_display()

    def input_decimal(self):
        if self.error:
            self.clear()
        if self.replace_display:
            self.display_value = "0."
            self.replace_display = False
        elif len(self.display_value.split(".")) == 1:
            self.display_value += "."
        self.update_display()

    def choose_operator(self, operator: str):
        if self.error:
            return
        if self.pending_operator != "" and not self.replace_display:
            self.calculate()
            if self.error:
                return
        self.stored_value = float(self.display_value)
        self.pending_operator = operator
        self.replace_display = True

    def toggle_sign(self):
        if self.error or self.display_value == "0" or self.display_value == "0.0":
            return
        self.display_value = str(0.0 - float(self.display_value))
        self.update_display()

    def percent(self):
        if self.error:
            return
        self.display_value = str(float(self.display_value) / 100.0)
        self.replace_display = True
        self.update_display()

    def calculate(self) -> float:
        operator = self.pending_operator
        if self.error or operator == "":
            return self.value()
        right = float(self.display_value)
        if operator == "/" and right == 0.0:
            self.display_value = "Error"
            self.pending_operator = ""
            self.replace_display = True
            self.error = True
            self.update_display()
            return 0.0
        result = calculate_result(self.stored_value, right, operator)
        self.display_value = str(result)
        self.stored_value = result
        self.pending_operator = ""
        self.replace_display = True
        self.update_display()
        return result

    def press(self, kind: str, value: str):
        if kind == "digit":
            self.input_digit(value)
        elif kind == "decimal":
            self.input_decimal()
        elif kind == "operator":
            self.choose_operator(value)
        elif kind == "equals":
            self.calculate()
        elif value == "clear":
            self.clear()
        elif value == "sign":
            self.toggle_sign()
        else:
            self.percent()

    def key(self, label: str, value: str, kind: str, row: int, column: int) -> Button:
        key = Button()
        key.id = "key-" + value
        key.testID = "key-" + value
        key.text = label
        key.row = row
        key.column = column
        if kind == "operator" or kind == "equals":
            key.className = (
                "m-1 h-14 rounded-xl bg-amber-500 text-2xl font-bold text-white"
            )
        else:
            key.className = (
                "m-1 h-14 rounded-xl bg-slate-100 text-2xl font-semibold "
                "text-slate-950"
            )
        listener = CalculatorButtonListener(self, kind, value)
        key.on(Button.tapEvent, listener.handleEvent)
        return key

    def page(self) -> Page:
        keypad = GridLayout()
        keypad.rows = "auto,auto,auto,auto,auto"
        keypad.columns = "*,*,*,*"
        labels = [
            ("AC", "clear", "clear"),
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
        index = 0
        for label, value, kind in labels:
            keypad.addChild(self.key(label, value, kind, index // 4, index % 4))
            index += 1

        content = StackLayout()
        content.className = "bg-slate-900 p-5"
        content.verticalAlignment = "middle"
        title = Label()
        title.text = "PyJS Calculator"
        title.className = "mb-4 text-center text-2xl font-bold text-sky-300"
        content.addChild(title)
        content.addChild(self.display)
        content.addChild(keypad)

        page = Page()
        page.actionBarHidden = True
        page.className = "bg-slate-900"
        page.content = content
        return page


@js
def create_android_page() -> Page:
    return AndroidCalculator().page()


@js
def android_main():
    Application.run(create_android_page)


def run_android():
    project = NativeScriptProject(
        android_main,
        name="PyJS Calculator",
        app_id="org.pyjs.calculator",
    )
    device = project.run_android()
    print(f"PyJS Calculator is running on {device.identifier}.")
