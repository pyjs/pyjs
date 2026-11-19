from pyjs.android import (
    Activity,
    Bundle,
    Context,
    Intent,
    OnClickListener,
    TextView,
    View,
)


class OpenFromContext(OnClickListener):
    def __init__(self, context: Context):
        self.context = context

    def onClick(self, view: View) -> None:
        self.context.start_activity(Intent().set_class(self.context, ContextTarget)
            .add_flags(Intent.FLAG_ACTIVITY_NEW_TASK).put_string_extra("message", "Opened from context 日本語"))


class ContextLauncher(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        view = TextView(self)
        view.setText("Open through application context")
        view.setGravity(17)
        view.setOnClickListener(OpenFromContext(self.getApplicationContext()))
        self.setContentView(view)


class ContextTarget(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        intent = self.get_intent()
        assert intent is not None
        view = TextView(self)
        view.setText(intent.get_string_extra("message") or "Missing message")
        view.setGravity(17)
        self.setContentView(view)
