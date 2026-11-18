from pyjs.android import Activity, Bundle, Button, OnClickListener, View


class CountTap(OnClickListener):
    def __init__(self, button: Button):
        self.button = button
        self.count = 0

    def onClick(self, view: View) -> None:
        self.count += 1
        self.button.setText(str(self.count))


class TapActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        button = Button(self)
        button.setId(1001)
        button.setText("0")
        button.setOnClickListener(CountTap(button))
        self.setContentView(button)
