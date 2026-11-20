import pytest

from pyjs.android import parse_color
from pyjs.android.graphics import Canvas, Paint, PaintStyle
from pyjs.android.testing import run_on_main
from pyjs.java.concurrent import Runnable

pytestmark = pytest.mark.pyjs_android_jvm


class CurveCalls(Runnable):
    def run(self) -> None:
        canvas = Canvas()
        paint = Paint(Paint.ANTI_ALIAS_FLAG)
        paint.setColor(parse_color("#2463eb"))
        paint.setStyle(PaintStyle.FILL)
        canvas.drawCircle(30.0, 30.0, 20.0, paint)
        canvas.drawArc(60.0, 10.0, 100.0, 50.0, 0.0, -90.0, True, paint)
        paint.setStyle(PaintStyle.STROKE)
        paint.setStrokeWidth(3.0)
        canvas.drawCircle(30.0, 80.0, 20.0, paint)
        canvas.drawArc(60.0, 60.0, 100.0, 100.0, -90.0, 180.0, False, paint)


def test_canvas_circle_and_arc_native_calls_accept_paint_and_sweep_variants() -> None:
    run_on_main(CurveCalls())
