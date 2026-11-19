from pyjs.android import (
    Activity,
    Bundle,
    Intent,
    LinearLayout,
    OnClickListener,
    TextView,
    View,
    dp,
)
from pyjs.android.controls import Button
from pyjs.java import i32


class StartResult(OnClickListener):
    def __init__(self, activity: Activity):
        self.activity = activity

    def onClick(self, view: View) -> None:
        self.activity.start_activity_for_result(
            Intent().set_class(self.activity, ResultChildActivity), i32(42),
        )


class FinishResult(OnClickListener):
    def __init__(self, activity: Activity, accepted: bool):
        self.activity = activity
        self.accepted = accepted

    def onClick(self, view: View) -> None:
        if self.accepted:
            self.activity.set_result(Activity.RESULT_OK,
                Intent().put_string_extra("selection", "Chosen 日本語 😀"))
        self.activity.finish()


class ResultChildActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        self.set_result(Activity.RESULT_CANCELED)
        content = LinearLayout(self)
        content.setOrientation(LinearLayout.VERTICAL)
        content.setPadding(0, dp(self, 96), 0, 0)
        accept = Button(self)
        accept.setText("Accept selection")
        accept.setOnClickListener(FinishResult(self, True))
        cancel = Button(self)
        cancel.setText("Cancel selection")
        cancel.setOnClickListener(FinishResult(self, False))
        content.addView(accept)
        content.addView(cancel)
        self.setContentView(content)


class ResultParentActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        content = LinearLayout(self)
        content.setOrientation(LinearLayout.VERTICAL)
        content.setPadding(0, dp(self, 96), 0, 0)
        self.status = TextView(self)
        self.status.setId(i32(1001))
        self.status.setText("Ready")
        choose = Button(self)
        choose.setText("Choose")
        choose.setOnClickListener(StartResult(self))
        content.addView(self.status)
        content.addView(choose)
        self.setContentView(content)

    def on_activity_result(self, request_code: i32, result_code: i32, data: Intent | None) -> None:
        super().on_activity_result(request_code, result_code, data)
        assert request_code == 42
        if result_code == Activity.RESULT_OK:
            assert data is not None
            self.status.setText(data.get_string_extra("selection") or "Missing result")
        else:
            assert result_code == Activity.RESULT_CANCELED and data is None
            self.status.setText("Selection cancelled")
