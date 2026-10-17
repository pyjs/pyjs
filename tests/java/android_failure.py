from pyjs.android import Activity, Bundle, Button, OnClickListener, View


class FailureClickListener(OnClickListener):
    def onClick(self, view: View) -> None:
        value = 1 // 0


class FailureActivity(Activity):
    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)
        button = Button(self)
        button.setText("Fail with Python line")
        button.setOnClickListener(FailureClickListener())
        self.setContentView(button)


def main() -> int:
    activity = FailureActivity()
    activity.onCreate(Bundle())
    return 0
