"""OS-managed alarm delivery; callers own durable schedules and permissions."""

from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.android.appwidget import PendingIntent
from pyjs.java import i32


@jvm.native("android/app/AlarmManager")
class AlarmManager:
    RTC_WAKEUP: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    RTC: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    ELAPSED_REALTIME_WAKEUP: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2
    ELAPSED_REALTIME: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 3

    def set(self, alarm_type: i32, trigger_at: int, operation: PendingIntent) -> None: ...

    @jvm.native("android/app/AlarmManager", name="setAndAllowWhileIdle", invocation="virtual")
    def set_and_allow_while_idle(self, alarm_type: i32, trigger_at: int,
                               operation: PendingIntent) -> None: ...

    @jvm.native("android/app/AlarmManager", name="setExactAndAllowWhileIdle", invocation="virtual")
    def set_exact_and_allow_while_idle(self, alarm_type: i32, trigger_at: int,
                                     operation: PendingIntent) -> None: ...

    @jvm.native("android/app/AlarmManager", name="canScheduleExactAlarms", invocation="virtual")
    def can_schedule_exact_alarms(self) -> bool: ...

    def cancel(self, operation: PendingIntent) -> None: ...
