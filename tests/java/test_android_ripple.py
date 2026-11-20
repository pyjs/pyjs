import pytest

from pyjs.android import GradientDrawable, parse_color
from pyjs.android.controls import ImageButton
from pyjs.android.drawables import RippleDrawable, color_state_list
from pyjs.android.testing import application_context, run_on_main
from pyjs.java.concurrent import Runnable

pytestmark = pytest.mark.pyjs_android_jvm


class RippleBackgrounds(Runnable):
    def run(self) -> None:
        context = application_context()
        color = parse_color("#335f6368")
        colors = color_state_list(color)
        assert colors.getDefaultColor() == color
        assert color_state_list(0).getDefaultColor() == 0
        assert color_state_list(parse_color("#ffffffff")).getDefaultColor() == -1
        mask = GradientDrawable()
        mask.setColor(parse_color("#ffffff"))
        mask.setCornerRadius(24.0)
        content = GradientDrawable()
        content.setColor(parse_color("#ffeecc"))
        for ripple in [RippleDrawable(colors, None, None),
                       RippleDrawable(colors, None, mask),
                       RippleDrawable(colors, content, None),
                       RippleDrawable(colors, content, mask)]:
            button = ImageButton(context)
            button.setBackground(ripple)
            background = button.getBackground()
            assert background is ripple
            assert isinstance(background, RippleDrawable)
            assert background.isStateful()
        first = ImageButton(context)
        second = ImageButton(context)
        first.setBackground(RippleDrawable(colors, None, None))
        second.setBackground(RippleDrawable(colors, None, None))
        assert first.getBackground() is not second.getBackground()


def test_native_ripple_backgrounds_accept_optional_layers_and_preserve_view_ownership() -> None:
    run_on_main(RippleBackgrounds())
