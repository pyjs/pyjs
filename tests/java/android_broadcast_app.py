from pyjs.android import (
    Activity,
    BroadcastPendingResult,
    BroadcastReceiver,
    Bundle,
    Button,
    Context,
    Intent,
    IntentFilter,
    LinearLayout,
    OnClickListener,
    TextView,
    View,
    dp,
)
from pyjs.java.concurrent import Runnable, Thread


class FinishBroadcast(Runnable):
    def __init__(self, pending: BroadcastPendingResult, fail: bool):
        self.pending = pending
        self.fail = fail

    def run(self) -> None:
        try:
            if self.fail:
                raise ValueError("Injected write failure")
            self.pending.set_result_data("Saved 日本語 😀")
        except ValueError:
            self.pending.set_result_data("Save failed")
        finally:
            self.pending.finish()


class DeferredReceiver(BroadcastReceiver):
    def __init__(self, label: TextView):
        self.label = label
        self.pending: BroadcastPendingResult | None = None

    def on_receive(self, context: Context, intent: Intent) -> None:
        self.pending = self.go_async()
        assert self.pending is not None
        assert self.go_async() is None
        self.label.setText("Waiting for background save")


class CompletedReceiver(BroadcastReceiver):
    def __init__(self, label: TextView):
        self.label = label

    def on_receive(self, context: Context, intent: Intent) -> None:
        self.label.setText(self.get_result_data() or "No result")


class BroadcastAction(OnClickListener):
    def __init__(self, activity: BroadcastActivity, action: str):
        self.activity = activity
        self.action = action

    def onClick(self, view: View) -> None:
        activity = self.activity
        if self.action == "begin":
            activity.label.setText("Sending broadcast")
            activity.send_ordered_broadcast(
                Intent().set_action(activity.action).set_package(activity.get_package_name()),
                None, CompletedReceiver(activity.label), None, 0, "Initial", None,
            )
        else:
            pending = activity.receiver.pending
            assert pending is not None
            activity.receiver.pending = None
            try:
                Thread(FinishBroadcast(pending, self.action == "fail")).start()
            except Exception:
                pending.finish()
                raise


class BroadcastActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        root.setPadding(0, dp(self, 96), 0, 0)
        self.label = TextView(self)
        self.label.setId(1001)
        self.label.setText("Ready")
        root.addView(self.label)
        self.action = self.get_package_name() + ".DEFERRED_SAVE"
        self.receiver = DeferredReceiver(self.label)
        assert self.receiver.go_async() is None
        self.register_receiver(self.receiver, IntentFilter(self.action), Context.RECEIVER_NOT_EXPORTED)
        for action in ["begin", "save", "fail"]:
            button = Button(self)
            button.setText(action)
            button.setOnClickListener(BroadcastAction(self, action))
            root.addView(button)
        self.setContentView(root)

    def onDestroy(self) -> None:
        pending = self.receiver.pending
        if pending is not None:
            self.receiver.pending = None
            pending.finish()
        self.unregister_receiver(self.receiver)
        super().onDestroy()
