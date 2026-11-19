import pytest

from pyjs.android import Intent
from pyjs.android.appwidget import PendingIntent, get_activity_pending_intent
from pyjs.android.notifications import (
    Notification,
    NotificationBuilder,
    NotificationChannel,
    NotificationManager,
)
from pyjs.android.testing import application_context
from pyjs.java import i32

pytestmark = pytest.mark.pyjs_android_jvm


def test_notification_channels_and_payload_preserve_metadata() -> None:
    context = application_context()
    service = context.get_system_service("notification")
    assert isinstance(service, NotificationManager)
    assert context.get_system_service("pyjs-missing-service") is None
    assert context.check_self_permission("org.pyjs.MISSING_PERMISSION") == -1
    channel_id = "notification-bindings"
    channel = NotificationChannel(channel_id, "Reminders 日本語", NotificationManager.IMPORTANCE_DEFAULT)
    channel.set_description("Scheduled tasks")
    service.create_channel(channel)
    try:
        stored = service.get_channel(channel_id)
        assert stored is not None
        assert stored.get_id() == channel_id
        assert stored.get_name().to_string() == "Reminders 日本語"
        assert stored.get_description() == "Scheduled tasks"
        assert stored.get_importance() == NotificationManager.IMPORTANCE_DEFAULT
        builder = NotificationBuilder(context, channel_id)
        builder.set_content_title("Review 😀").set_content_text("Bring the checklist")
        builder.set_small_icon(context.get_resources().get_identifier("ic_dialog_info", "drawable", "android"))
        builder.set_category(Notification.CATEGORY_REMINDER).set_visibility(Notification.VISIBILITY_PRIVATE)
        builder.set_auto_cancel(True).set_only_alert_once(True).set_when(1_900_000_000_123)
        intent = Intent().set_action("org.pyjs.OPEN_REMINDER").set_package(context.get_package_name())
        pending = get_activity_pending_intent(context, i32(981), intent, PendingIntent.FLAG_IMMUTABLE)
        try:
            builder.set_content_intent(pending).set_delete_intent(None).add_action(i32(0), "Open", pending)
            notification = builder.build()
            assert notification.get_channel_id() == channel_id
            assert notification.when == 1_900_000_000_123
            assert notification.visibility == Notification.VISIBILITY_PRIVATE
            assert notification.flags & Notification.FLAG_AUTO_CANCEL != 0
            assert notification.flags & Notification.FLAG_ONLY_ALERT_ONCE != 0
            assert notification.extras.get_string("android.title") == "Review 😀"
            assert notification.extras.get_string("android.text") == "Bring the checklist"
        finally:
            pending.cancel()
    finally:
        service.delete_channel(channel_id)
    assert service.get_channel(channel_id) is None
