"""Native notification channels, payloads and publication on Android 26+."""

from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.android import Bundle, CharSequence, Context, JavaCharSequence, Parcelable
from pyjs.android.appwidget import PendingIntent
from pyjs.java import JVMArray, i32


@jvm.native("android/app/Notification")
class Notification(Parcelable):
    CATEGORY_REMINDER: ClassVar[Annotated[str, jvm.field(writable=False)]] = "reminder"
    VISIBILITY_SECRET: ClassVar[Annotated[i32, jvm.field(writable=False)]] = -1
    VISIBILITY_PRIVATE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    VISIBILITY_PUBLIC: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    FLAG_ONLY_ALERT_ONCE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 8
    FLAG_AUTO_CANCEL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 16

    extras: Annotated[Bundle, jvm.field(writable=False)]
    flags: Annotated[i32, jvm.field(writable=False)]
    visibility: Annotated[i32, jvm.field(writable=False)]
    when: Annotated[int, jvm.field(writable=False)]

    @jvm.native("android/app/Notification", name="getChannelId", invocation="virtual")
    def get_channel_id(self) -> str | None: ...


@jvm.native("android/app/Notification$Builder")
class NotificationBuilder:
    def __init__(self, context: Context, channel_id: str) -> None: ...

    @jvm.native("android/app/Notification$Builder", name="setContentTitle", invocation="virtual")
    def set_content_title(self, title: CharSequence) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setContentText", invocation="virtual")
    def set_content_text(self, text: CharSequence) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setSmallIcon", invocation="virtual")
    def set_small_icon(self, icon: i32) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setContentIntent", invocation="virtual")
    def set_content_intent(self, intent: PendingIntent | None) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setDeleteIntent", invocation="virtual")
    def set_delete_intent(self, intent: PendingIntent | None) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setAutoCancel", invocation="virtual")
    def set_auto_cancel(self, value: bool) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setOnlyAlertOnce", invocation="virtual")
    def set_only_alert_once(self, value: bool) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setCategory", invocation="virtual")
    def set_category(self, value: str) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setVisibility", invocation="virtual")
    def set_visibility(self, value: i32) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="setWhen", invocation="virtual")
    def set_when(self, milliseconds: int) -> NotificationBuilder: ...

    @jvm.native("android/app/Notification$Builder", name="addAction", invocation="virtual")
    def add_action(self, icon: i32, title: CharSequence, intent: PendingIntent) -> NotificationBuilder: ...

    def build(self) -> Notification: ...


@jvm.native("android/app/NotificationChannel")
class NotificationChannel:
    def __init__(self, channel_id: str, name: CharSequence, importance: i32) -> None: ...

    @jvm.native("android/app/NotificationChannel", name="getId", invocation="virtual")
    def get_id(self) -> str: ...

    @jvm.native("android/app/NotificationChannel", name="getName", invocation="virtual")
    def get_name(self) -> JavaCharSequence: ...

    @jvm.native("android/app/NotificationChannel", name="getImportance", invocation="virtual")
    def get_importance(self) -> i32: ...

    @jvm.native("android/app/NotificationChannel", name="setDescription", invocation="virtual")
    def set_description(self, description: str | None) -> None: ...

    @jvm.native("android/app/NotificationChannel", name="getDescription", invocation="virtual")
    def get_description(self) -> str | None: ...


@jvm.native("android/service/notification/StatusBarNotification")
class StatusBarNotification:
    @jvm.native("android/service/notification/StatusBarNotification", name="getId", invocation="virtual")
    def get_id(self) -> i32: ...

    @jvm.native("android/service/notification/StatusBarNotification", name="getTag", invocation="virtual")
    def get_tag(self) -> str | None: ...

    @jvm.native("android/service/notification/StatusBarNotification", name="getNotification", invocation="virtual")
    def get_notification(self) -> Notification: ...


@jvm.native("android/app/NotificationManager")
class NotificationManager:
    IMPORTANCE_NONE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    IMPORTANCE_LOW: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2
    IMPORTANCE_DEFAULT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 3
    IMPORTANCE_HIGH: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 4

    @jvm.native("android/app/NotificationManager", name="createNotificationChannel", invocation="virtual")
    def create_channel(self, channel: NotificationChannel) -> None: ...

    @jvm.native("android/app/NotificationManager", name="getNotificationChannel", invocation="virtual")
    def get_channel(self, channel_id: str) -> NotificationChannel | None: ...

    @jvm.native("android/app/NotificationManager", name="deleteNotificationChannel", invocation="virtual")
    def delete_channel(self, channel_id: str) -> None: ...

    @jvm.native("android/app/NotificationManager", name="areNotificationsEnabled", invocation="virtual")
    def are_notifications_enabled(self) -> bool: ...

    def notify(self, tag: str | None, notification_id: i32, notification: Notification) -> None: ...

    def cancel(self, tag: str | None, notification_id: i32) -> None: ...

    @jvm.native("android/app/NotificationManager", name="getActiveNotifications", invocation="virtual")
    def get_active_notifications(self) -> JVMArray[StatusBarNotification]: ...
