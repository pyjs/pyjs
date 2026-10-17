"""Calculator behavior shared by the browser and native Android views."""

from pyjs import js, jvm


@js
@jvm.native("java/lang/Double", name="parseDouble")
def parse_number(value: str) -> float:
    return float(value)


@js
@jvm.native("java/lang/Double", name="toString")
def format_number(value: float) -> str:
    return str(value)


@js
def calculate_result(left: float, right: float, operator: str) -> float:
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    return left / right


@js
class Calculator:
    def __init__(self, initial_value: str = "0") -> None:
        self.display_value = initial_value
        self.stored_value = 0.0
        self.pending_operator = ""
        self.replace_display = True
        self.error = False

    def clear(self):
        self.display_value = "0"
        self.stored_value = 0.0
        self.pending_operator = ""
        self.replace_display = True
        self.error = False

    def value(self) -> float:
        if self.error:
            return 0.0
        return parse_number(self.display_value)

    def input_digit(self, digit: str):
        if self.error:
            self.clear()
        if self.replace_display or self.display_value == "0":
            self.display_value = digit
            self.replace_display = False
        else:
            self.display_value = self.display_value + digit

    def input_decimal(self):
        if self.error:
            self.clear()
        value = self.display_value
        if self.replace_display:
            self.display_value = "0."
            self.replace_display = False
        elif "." not in value:
            self.display_value = value + "."

    def toggle_sign(self):
        value = self.display_value
        if self.error or value == "0" or value == "0.0":
            return
        self.display_value = format_number(0.0 - parse_number(value))

    def percent(self):
        if self.error:
            return
        self.display_value = format_number(parse_number(self.display_value) / 100.0)
        self.replace_display = True

    def choose_operator(self, operator: str):
        if self.error:
            return
        if self.pending_operator != "" and not self.replace_display:
            self.calculate()
            if self.error:
                return
        self.stored_value = parse_number(self.display_value)
        self.pending_operator = operator
        self.replace_display = True

    def calculate(self) -> float:
        operator = self.pending_operator
        if self.error or operator == "":
            return self.value()
        right = parse_number(self.display_value)
        if operator == "/" and right == 0.0:
            self.display_value = "Error"
            self.pending_operator = ""
            self.replace_display = True
            self.error = True
            return 0.0
        result = calculate_result(self.stored_value, right, operator)
        self.display_value = format_number(result)
        self.stored_value = result
        self.pending_operator = ""
        self.replace_display = True
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
