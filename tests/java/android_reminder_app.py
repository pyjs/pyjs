from pyjs.android import (
    Activity,
    BroadcastReceiver,
    Bundle,
    Button,
    Context,
    Intent,
    LinearLayout,
    OnClickListener,
    TextView,
    View,
)
from pyjs.android.alarms import AlarmManager
from pyjs.android.appwidget import (
    PendingIntent,
    get_activity_pending_intent,
    get_broadcast_pending_intent,
)
from pyjs.android.notifications import (
    NotificationBuilder,
    NotificationChannel,
    NotificationManager,
)
from pyjs.java import JVMArray, current_time_millis, i32
from pyjs.java.errors import SecurityException


class ReminderReceiver(BroadcastReceiver):
    def on_receive(self, context: Context, intent: Intent) -> None:
        manager = context.get_system_service("notification")
        assert isinstance(manager, NotificationManager)
        if not manager.are_notifications_enabled():
            return
        manager.create_channel(NotificationChannel("reminders", "Reminders",
                                                    NotificationManager.IMPORTANCE_DEFAULT))
        open_intent = Intent().set_class(context, ReminderActivity).set_action("org.pyjs.REMINDER_OPEN")
        pending = get_activity_pending_intent(context, i32(1), open_intent, PendingIntent.FLAG_IMMUTABLE)
        builder = NotificationBuilder(context, "reminders")
        builder.set_content_title("Scheduled reminder arrived").set_content_text("Open the reminder")
        builder.set_small_icon(context.get_resources().get_identifier("ic_dialog_info", "drawable", "android"))
        builder.set_content_intent(pending).set_auto_cancel(True)
        manager.notify("scheduled", i32(1), builder.build())


class ReminderAction(OnClickListener):
    def __init__(self, activity: ReminderActivity, action: str):
        self.activity = activity
        self.action = action

    def onClick(self, view: View) -> None:
        activity = self.activity
        if self.action == "Enable notifications":
            permissions = JVMArray[str](1)
            permissions[0] = "android.permission.POST_NOTIFICATIONS"
            activity.request_permissions(permissions, i32(1))
            return
        alarms = activity.get_system_service("alarm")
        assert isinstance(alarms, AlarmManager)
        intent = Intent().set_class_name(activity.get_package_name(),
                                        activity.get_package_name() + ".PyjsAndroid$ReminderReceiver")
        pending = get_broadcast_pending_intent(activity, i32(1), intent, PendingIntent.FLAG_IMMUTABLE)
        try:
            alarms.set_exact_and_allow_while_idle(AlarmManager.RTC_WAKEUP,
                                                  current_time_millis() + 20_000, pending)
        except SecurityException:
            activity.status.setText("Exact alarms unavailable")
            return
        activity.finish()


class ReminderActivity(Activity):
    status: TextView

    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        self.status = TextView(self)
        manager = self.get_system_service("notification")
        assert isinstance(manager, NotificationManager)
        self.status.setText("Notifications enabled" if manager.are_notifications_enabled()
                            else "Notifications disabled")
        intent = self.get_intent()
        if intent is not None and intent.get_action() == "org.pyjs.REMINDER_OPEN":
            self.status.setText("Reminder opened from notification")
        root.addView(self.status)
        for action in ["Enable notifications", "Schedule reminder"]:
            button = Button(self)
            button.setText(action)
            button.setOnClickListener(ReminderAction(self, action))
            root.addView(button)
        self.setContentView(root)

    def on_request_permissions_result(self, request_code: i32,
                                      permissions: JVMArray[str],
                                      grant_results: JVMArray[i32]) -> None:
        super().on_request_permissions_result(request_code, permissions, grant_results)
        self.status.setText("Permission granted" if len(grant_results) > 0 and grant_results[0] == 0
                            else "Permission denied")


def main() -> int:
    ReminderReceiver()
    ReminderActivity().onCreate(None)
    return 0
