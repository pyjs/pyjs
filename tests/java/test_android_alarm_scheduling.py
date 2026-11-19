from typing import Annotated

import pytest

from pyjs import jvm
from pyjs.android import Intent
from pyjs.android.alarms import AlarmManager
from pyjs.android.appwidget import PendingIntent, get_broadcast_pending_intent
from pyjs.android.notifications import (
    NotificationBuilder,
    NotificationChannel,
    NotificationManager,
)
from pyjs.android.testing import application_context
from pyjs.java import i32

pytestmark = [pytest.mark.pyjs_android_jvm, pytest.mark.pyjs_android_robolectric]


@jvm.native("org/robolectric/shadows/ShadowAlarmManager$ScheduledAlarm")
class ScheduledAlarm:
    triggerAtTime: Annotated[int, jvm.field(writable=False)]
    type: Annotated[i32, jvm.field(writable=False)]
    allowWhileIdle: Annotated[bool, jvm.field(writable=False)]

    def getWindowLengthMs(self) -> int: ...


@jvm.native("org/robolectric/shadows/ShadowAlarmManager")
class AlarmShadow:
    def peekNextScheduledAlarm(self) -> ScheduledAlarm | None: ...


@jvm.native("org/robolectric/Shadows", name="shadowOf")
def alarm_shadow(manager: AlarmManager) -> AlarmShadow: ...


@jvm.native("org/robolectric/shadows/ShadowAlarmManager", name="setCanScheduleExactAlarms")
def exact_permission(value: bool) -> None: ...


@jvm.native("org/robolectric/shadows/ShadowNotificationManager")
class NotificationShadow:
    def setNotificationsEnabled(self, value: bool) -> None: ...


@jvm.native("org/robolectric/Shadows", name="shadowOf")
def notification_shadow(manager: NotificationManager) -> NotificationShadow: ...


def test_alarm_replacement_cancellation_and_exact_permission_state() -> None:
    context = application_context()
    manager = context.get_system_service("alarm")
    assert isinstance(manager, AlarmManager)
    shadow = alarm_shadow(manager)
    intent = Intent().set_action("org.pyjs.ALARM_TEST").set_package(context.get_package_name())
    pending = get_broadcast_pending_intent(context, i32(782), intent, PendingIntent.FLAG_IMMUTABLE)
    try:
        exact_permission(False)
        assert not manager.can_schedule_exact_alarms()
        manager.set_and_allow_while_idle(AlarmManager.RTC_WAKEUP, 1_900_000_000_123, pending)
        alarm = shadow.peekNextScheduledAlarm()
        assert alarm is not None and alarm.triggerAtTime == 1_900_000_000_123
        assert alarm.type == AlarmManager.RTC_WAKEUP and alarm.allowWhileIdle
        assert alarm.getWindowLengthMs() != 0
        exact_permission(True)
        assert manager.can_schedule_exact_alarms()
        manager.set_exact_and_allow_while_idle(AlarmManager.RTC_WAKEUP, 1_900_000_001_234, pending)
        alarm = shadow.peekNextScheduledAlarm()
        assert alarm is not None and alarm.triggerAtTime == 1_900_000_001_234
        assert alarm.getWindowLengthMs() == 0
        manager.cancel(pending)
        assert shadow.peekNextScheduledAlarm() is None
        manager.set(AlarmManager.ELAPSED_REALTIME, 90_000, pending)
        alarm = shadow.peekNextScheduledAlarm()
        assert alarm is not None and alarm.type == AlarmManager.ELAPSED_REALTIME
        assert alarm.triggerAtTime == 90_000 and not alarm.allowWhileIdle
    finally:
        manager.cancel(pending)
        pending.cancel()


def test_notification_tags_replace_and_cancel_independently_of_global_permission() -> None:
    context = application_context()
    manager = context.get_system_service("notification")
    assert isinstance(manager, NotificationManager)
    shadow = notification_shadow(manager)
    shadow.setNotificationsEnabled(False)
    assert not manager.are_notifications_enabled()
    shadow.setNotificationsEnabled(True)
    assert manager.are_notifications_enabled()
    channel_id = "notification-publication"
    manager.create_channel(NotificationChannel(channel_id, "Alerts", NotificationManager.IMPORTANCE_DEFAULT))
    builder = NotificationBuilder(context, channel_id)
    builder.set_small_icon(context.get_resources().get_identifier("ic_dialog_info", "drawable", "android"))
    try:
        manager.notify("one", i32(17), builder.set_content_title("First").build())
        manager.notify("two", i32(17), builder.set_content_title("Second").build())
        manager.notify("one", i32(17), builder.set_content_title("Replaced").build())
        active = manager.get_active_notifications()
        assert len(active) == 2
        found = False
        for notification in active:
            if notification.get_tag() == "one":
                found = True
                assert notification.get_id() == 17
                assert notification.get_notification().extras.get_string("android.title") == "Replaced"
        assert found
        manager.cancel("one", i32(17))
        active = manager.get_active_notifications()
        assert len(active) == 1 and active[0].get_tag() == "two"
    finally:
        manager.cancel("one", i32(17))
        manager.cancel("two", i32(17))
        manager.delete_channel(channel_id)
