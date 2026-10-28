"""Native multi-pointer events for Android Views."""
from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.java import JVMArray, f32, i32


@jvm.native("android/view/MotionEvent$PointerProperties")
class PointerProperties:
    id: Annotated[i32, jvm.field()]
    toolType: Annotated[i32, jvm.field()]

    def __init__(self) -> None: ...


@jvm.native("android/view/MotionEvent$PointerCoords")
class PointerCoords:
    x: Annotated[f32, jvm.field()]
    y: Annotated[f32, jvm.field()]
    pressure: Annotated[f32, jvm.field()]
    size: Annotated[f32, jvm.field()]

    def __init__(self) -> None: ...


@jvm.native("android/view/MotionEvent")
class MotionEvent:
    ACTION_DOWN: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    ACTION_UP: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    ACTION_MOVE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2
    ACTION_CANCEL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 3
    ACTION_POINTER_DOWN: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 5
    ACTION_POINTER_UP: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 6
    ACTION_POINTER_INDEX_SHIFT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 8
    TOOL_TYPE_FINGER: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1

    def getActionMasked(self) -> i32: ...
    def getActionIndex(self) -> i32: ...
    def getPointerCount(self) -> i32: ...
    def getPointerId(self, index: i32) -> i32: ...
    def findPointerIndex(self, pointer_id: i32) -> i32: ...
    def getX(self) -> f32: ...
    def getY(self) -> f32: ...
    def recycle(self) -> None: ...

    @jvm.native("android/view/MotionEvent", name="getX", invocation="virtual")
    def get_x_at(self, index: i32) -> f32: ...

    @jvm.native("android/view/MotionEvent", name="getY", invocation="virtual")
    def get_y_at(self, index: i32) -> f32: ...


@jvm.native("android/view/MotionEvent", name="obtain")
def obtain_motion_event(down_time: int, event_time: int, action: i32,
                        x: f32, y: f32, meta_state: i32) -> MotionEvent: ...


@jvm.native("android/view/MotionEvent", name="obtain")
def obtain_pointer_event(down_time: int, event_time: int, action: i32, pointer_count: i32,
                         properties: JVMArray[PointerProperties], coords: JVMArray[PointerCoords],
                         meta_state: i32, button_state: i32, x_precision: f32, y_precision: f32,
                         device_id: i32, edge_flags: i32, source: i32, flags: i32) -> MotionEvent: ...


@jvm.native("android/os/SystemClock", name="uptimeMillis")
def uptime_millis() -> int:
    """Monotonic Android uptime, the time base required by MotionEvent."""
    ...
