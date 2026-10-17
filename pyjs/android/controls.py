"""Generated Android controls used by note and checklist editors."""

from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.android import Button, Context, Drawable, Editable, TextView, View, ViewGroup
from pyjs.java import i32


@jvm.native("java/lang/Object")
class Object:
    pass


@jvm.native("android/text/InputType", interface=True)
class InputType(Object):
    TYPE_CLASS_NUMBER: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2
    TYPE_CLASS_TEXT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    TYPE_NULL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    TYPE_NUMBER_FLAG_DECIMAL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 8192
    TYPE_NUMBER_FLAG_SIGNED: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 4096
    TYPE_TEXT_FLAG_AUTO_CORRECT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = (
        32768
    )
    TYPE_TEXT_FLAG_CAP_SENTENCES: ClassVar[Annotated[i32, jvm.field(writable=False)]] = (
        16384
    )
    TYPE_TEXT_FLAG_MULTI_LINE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = (
        131072
    )
    TYPE_TEXT_FLAG_NO_SUGGESTIONS: ClassVar[Annotated[i32, jvm.field(writable=False)]] = (
        524288
    )
    TYPE_TEXT_VARIATION_EMAIL_ADDRESS: ClassVar[
        Annotated[i32, jvm.field(writable=False)]
    ] = 32
    TYPE_TEXT_VARIATION_LONG_MESSAGE: ClassVar[
        Annotated[i32, jvm.field(writable=False)]
    ] = 80
    TYPE_TEXT_VARIATION_PASSWORD: ClassVar[Annotated[i32, jvm.field(writable=False)]] = (
        128
    )
    TYPE_TEXT_VARIATION_URI: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 16
    TYPE_TEXT_VARIATION_VISIBLE_PASSWORD: ClassVar[
        Annotated[i32, jvm.field(writable=False)]
    ] = 144


@jvm.native("android/widget/CompoundButton")
class CompoundButton(Button):
    def __init__(self, context: Context) -> None:
        pass

    def toggle(self) -> None:
        pass

    @jvm.native(
        "android/widget/CompoundButton",
        name="isChecked",
        invocation="virtual",
    )
    def is_checked(self) -> bool:
        pass

    @jvm.native(
        "android/widget/CompoundButton",
        name="setChecked",
        invocation="virtual",
    )
    def set_checked(self, checked: bool) -> None:
        pass

    @jvm.native(
        "android/widget/CompoundButton",
        name="setOnCheckedChangeListener",
        invocation="virtual",
    )
    def set_on_checked_change_listener(
        self,
        listener: OnCheckedChangeListener | None,
    ) -> None:
        pass

    @jvm.native(
        "android/widget/CompoundButton",
        name="setButtonDrawable",
        invocation="virtual",
    )
    def set_button_drawable(self, drawable: Drawable | None) -> None:
        pass


@jvm.native("android/widget/CheckBox")
class CheckBox(CompoundButton):
    def __init__(self, context: Context) -> None:
        pass


@jvm.native("android/widget/CompoundButton$OnCheckedChangeListener", interface=True)
class OnCheckedChangeListener(Object):
    @jvm.native(
        "android/widget/CompoundButton$OnCheckedChangeListener",
        name="onCheckedChanged",
        invocation="virtual",
    )
    def on_checked_changed(self, button: CompoundButton, checked: bool) -> None:
        pass


@jvm.native("android/widget/EditText")
class EditText(TextView):
    def __init__(self, context: Context) -> None:
        pass

    @jvm.native(
        "android/widget/EditText",
        name="getText",
        invocation="virtual",
    )
    def get_text(self) -> Editable:
        pass

    @jvm.native(
        "android/widget/EditText",
        name="setSelection",
        invocation="virtual",
    )
    def set_selection(self, index: i32) -> None:
        pass

    @jvm.native(
        "android/widget/EditText",
        name="setSelection",
        invocation="virtual",
    )
    def set_selection_range(self, start: i32, stop: i32) -> None:
        pass

    @jvm.native(
        "android/widget/EditText",
        name="selectAll",
        invocation="virtual",
    )
    def select_all(self) -> None:
        pass


@jvm.native("android/widget/FrameLayout")
class FrameLayout(ViewGroup):
    def __init__(self, context: Context) -> None:
        pass

    @jvm.native(
        "android/widget/FrameLayout",
        name="setForegroundGravity",
        invocation="virtual",
    )
    def set_foreground_gravity(self, foreground_gravity: i32) -> None:
        pass


@jvm.native("android/widget/ImageView")
class ImageView(View):
    def __init__(self, context: Context) -> None:
        pass

    @jvm.native(
        "android/widget/ImageView",
        name="setAdjustViewBounds",
        invocation="virtual",
    )
    def set_adjust_view_bounds(self, adjust_view_bounds: bool) -> None:
        pass

    @jvm.native(
        "android/widget/ImageView",
        name="setMaxWidth",
        invocation="virtual",
    )
    def set_max_width(self, max_width: i32) -> None:
        pass

    @jvm.native(
        "android/widget/ImageView",
        name="setMaxHeight",
        invocation="virtual",
    )
    def set_max_height(self, max_height: i32) -> None:
        pass

    @jvm.native(
        "android/widget/ImageView",
        name="setImageResource",
        invocation="virtual",
    )
    def set_image_resource(self, res_id: i32) -> None:
        pass

    @jvm.native(
        "android/widget/ImageView",
        name="setImageDrawable",
        invocation="virtual",
    )
    def set_image_drawable(self, drawable: Drawable | None) -> None:
        pass

    @jvm.native(
        "android/widget/ImageView",
        name="setImageAlpha",
        invocation="virtual",
    )
    def set_image_alpha(self, alpha: i32) -> None:
        pass


@jvm.native("android/widget/ImageButton")
class ImageButton(ImageView):
    def __init__(self, context: Context) -> None:
        pass


@jvm.native("android/widget/ScrollView")
class ScrollView(FrameLayout):
    def __init__(self, context: Context) -> None:
        pass

    @jvm.native(
        "android/widget/ScrollView",
        name="setFillViewport",
        invocation="virtual",
    )
    def set_fill_viewport(self, fill_viewport: bool) -> None:
        pass

    @jvm.native(
        "android/widget/ScrollView",
        name="setSmoothScrollingEnabled",
        invocation="virtual",
    )
    def set_smooth_scrolling_enabled(self, enabled: bool) -> None:
        pass

    @jvm.native(
        "android/widget/ScrollView",
        name="smoothScrollBy",
        invocation="virtual",
    )
    def smooth_scroll_by(self, dx: i32, dy: i32) -> None:
        pass

    @jvm.native(
        "android/widget/ScrollView",
        name="smoothScrollTo",
        invocation="virtual",
    )
    def smooth_scroll_to(self, x: i32, y: i32) -> None:
        pass

    def fling(self, velocity_y: i32) -> None:
        pass

    @jvm.native(
        "android/widget/ScrollView",
        name="scrollTo",
        invocation="virtual",
    )
    def scroll_to(self, x: i32, y: i32) -> None:
        pass


__all__ = [
    "CheckBox",
    "CompoundButton",
    "EditText",
    "FrameLayout",
    "ImageButton",
    "ImageView",
    "InputType",
    "OnCheckedChangeListener",
    "ScrollView",
]
