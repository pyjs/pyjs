"""Native drawing declarations and override ABIs, checked against Android."""
import pytest

from pyjs.android.api import AndroidAPI
from pyjs.java import read_jvm_class, transpile_jvm


def test_canvas_touch_and_scale_overrides_have_android_descriptors():
    compilation = transpile_jvm('''from pyjs.android import Activity, Context, TextView, View
from pyjs.android.graphics import Canvas, Paint, PaintStyle
from pyjs.android.motion import MotionEvent, PointerCoords, PointerProperties, obtain_pointer_event, uptime_millis
from pyjs.android.gestures import OnScaleGestureListener, ScaleGestureDetector
from pyjs.java import JVMArray, f32
class Scale(OnScaleGestureListener):
    def onScaleBegin(self, detector: ScaleGestureDetector) -> bool:
        return True
    def onScale(self, detector: ScaleGestureDetector) -> bool:
        return detector.getScaleFactor() > 0.0
    def onScaleEnd(self, detector: ScaleGestureDetector) -> None:
        pass
class Drawing(View):
    def __init__(self, context: Context):
        super().__init__(context)
        self.paint = Paint(Paint.ANTI_ALIAS_FLAG)
        self.detector = ScaleGestureDetector(context, Scale())
    def onDraw(self, canvas: Canvas) -> None:
        saved = canvas.save()
        self.paint.setStyle(PaintStyle.STROKE)
        canvas.scale(f32(2.0), f32(2.0))
        canvas.drawLine(f32(0.0), f32(0.0), f32(10.0), f32(10.0), self.paint)
        canvas.restoreToCount(saved)
    def onTouchEvent(self, event: MotionEvent) -> bool:
        self.detector.onTouchEvent(event)
        self.invalidate()
        return event.getActionMasked() == MotionEvent.ACTION_DOWN
class DrawingLabel(TextView):
    def __init__(self, context: Context):
        super().__init__(context)
    def onDraw(self, canvas: Canvas) -> None:
        super().onDraw(canvas)
        canvas.drawColor(0)
def main() -> int:
    drawing = Drawing(Activity())
    drawing.invalidate()
    label = DrawingLabel(Activity())
    label.invalidate()
    properties = JVMArray[PointerProperties](1)
    prop = PointerProperties()
    prop.id = 0
    prop.toolType = MotionEvent.TOOL_TYPE_FINGER
    properties[0] = prop
    coords = JVMArray[PointerCoords](1)
    point = PointerCoords()
    point.x = f32(12.0)
    point.y = f32(18.0)
    point.pressure = f32(1.0)
    point.size = f32(1.0)
    coords[0] = point
    now = uptime_millis()
    event = obtain_pointer_event(now, now, MotionEvent.ACTION_DOWN, 1, properties, coords,
                                 0, 0, f32(1.0), f32(1.0), 0, 0, 0x1002, 0)
    drawing.dispatchTouchEvent(event)
    event.recycle()
    return 0
''', filename="drawing.py")
    classes = [read_jvm_class(value) for value in compilation.classes.values()]
    drawing = next(value for value in classes if value.super_name == "android/view/View")
    methods = {(method.name, method.descriptor) for method in drawing.methods}
    assert ("onDraw", "(Landroid/graphics/Canvas;)V") in methods
    assert ("onTouchEvent", "(Landroid/view/MotionEvent;)Z") in methods
    label = next(value for value in classes if value.super_name == "android/widget/TextView")
    assert ("onDraw", "(Landroid/graphics/Canvas;)V") in {
        (method.name, method.descriptor) for method in label.methods}
    scale = next(value for value in classes
                 if "android/view/ScaleGestureDetector$OnScaleGestureListener" in value.interfaces)
    assert ("onScale", "(Landroid/view/ScaleGestureDetector;)Z") in {
        (method.name, method.descriptor) for method in scale.methods}


def test_drawing_surface_matches_installed_android_sdk():
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 is not installed")
    expected = {
        "android/graphics/Canvas": {
            ("save", "()I"), ("restoreToCount", "(I)V"), ("translate", "(FF)V"),
            ("scale", "(FF)V"), ("drawColor", "(I)V"),
            ("drawLine", "(FFFFLandroid/graphics/Paint;)V"),
            ("drawRoundRect", "(FFFFFFLandroid/graphics/Paint;)V"),
            ("drawText", "(Ljava/lang/String;FFLandroid/graphics/Paint;)V"),
        },
        "android/graphics/Paint": {
            ("<init>", "(I)V"), ("setColor", "(I)V"), ("setTextSize", "(F)V"),
            ("setStrokeWidth", "(F)V"), ("setStyle", "(Landroid/graphics/Paint$Style;)V"),
            ("measureText", "(Ljava/lang/String;)F"),
        },
        "android/view/View": {
            ("invalidate", "()V"), ("onDraw", "(Landroid/graphics/Canvas;)V"),
            ("onTouchEvent", "(Landroid/view/MotionEvent;)Z"), ("performClick", "()Z"),
            ("dispatchTouchEvent", "(Landroid/view/MotionEvent;)Z"),
            ("getParent", "()Landroid/view/ViewParent;"),
        },
        "android/view/MotionEvent": {
            ("getActionMasked", "()I"), ("getActionIndex", "()I"), ("getPointerCount", "()I"),
            ("getPointerId", "(I)I"), ("findPointerIndex", "(I)I"),
            ("getX", "()F"), ("getY", "()F"), ("getX", "(I)F"), ("getY", "(I)F"),
            ("recycle", "()V"), ("obtain", "(JJIFFI)Landroid/view/MotionEvent;"),
            ("obtain", "(JJII[Landroid/view/MotionEvent$PointerProperties;[Landroid/view/MotionEvent$PointerCoords;IIFFIIII)Landroid/view/MotionEvent;"),
        },
        "android/view/MotionEvent$PointerProperties": {("<init>", "()V")},
        "android/view/MotionEvent$PointerCoords": {("<init>", "()V")},
        "android/os/SystemClock": {("uptimeMillis", "()J")},
        "android/view/ScaleGestureDetector": {
            ("<init>", "(Landroid/content/Context;Landroid/view/ScaleGestureDetector$OnScaleGestureListener;)V"),
            ("onTouchEvent", "(Landroid/view/MotionEvent;)Z"), ("isInProgress", "()Z"),
            ("getScaleFactor", "()F"), ("getFocusX", "()F"), ("getFocusY", "()F"),
        },
    }
    with api:
        for name, methods in expected.items():
            actual = api.require_class(name)
            assert methods <= {(method.name, method.descriptor) for method in actual.methods}
        style = api.require_class("android/graphics/Paint$Style")
        assert {("FILL", "Landroid/graphics/Paint$Style;"), ("STROKE", "Landroid/graphics/Paint$Style;")} <= {
            (field.name, field.descriptor) for field in style.fields}
        for name, fields in {
            "android/view/MotionEvent$PointerProperties": {("id", "I"), ("toolType", "I")},
            "android/view/MotionEvent$PointerCoords": {("x", "F"), ("y", "F"), ("pressure", "F"), ("size", "F")},
        }.items():
            assert fields <= {(field.name, field.descriptor) for field in api.require_class(name).fields}
