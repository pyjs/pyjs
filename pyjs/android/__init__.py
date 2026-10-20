"""Typed declarations for Android framework APIs used by PyJS applications."""

from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.java import JVMArray, f32, i32
from pyjs.java.concurrent import Runnable
from pyjs.java.io import File
from pyjs.java.primitives import Reference

from .api import AndroidAPI, AndroidAvailability, AndroidNullability

CharSequence = Annotated[str, Reference("java/lang/CharSequence")]


@jvm.native("android/os/Build$VERSION")
class BuildVersion:
    SDK_INT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0


@jvm.native("android/content/SharedPreferences$Editor", interface=True)
class SharedPreferencesEditor:
    def commit(self) -> bool: ...

    @jvm.native(
        "android/content/SharedPreferences$Editor",
        name="putString",
        invocation="virtual",
    )
    def put_string(self, key: str, value: str | None) -> SharedPreferencesEditor:
        return self

    @jvm.native(
        "android/content/SharedPreferences$Editor",
        name="putInt",
        invocation="virtual",
    )
    def put_int(self, key: str, value: i32) -> SharedPreferencesEditor:
        return self

    @jvm.native(
        "android/content/SharedPreferences$Editor",
        name="putLong",
        invocation="virtual",
    )
    def put_long(self, key: str, value: int) -> SharedPreferencesEditor:
        return self

    @jvm.native(
        "android/content/SharedPreferences$Editor",
        name="putBoolean",
        invocation="virtual",
    )
    def put_boolean(self, key: str, value: bool) -> SharedPreferencesEditor:
        return self

    @jvm.native(
        "android/content/SharedPreferences$Editor",
        name="apply",
        invocation="virtual",
    )
    def apply(self) -> None:
        pass


@jvm.native("android/content/SharedPreferences", interface=True)
class SharedPreferences:
    @jvm.native(
        "android/content/SharedPreferences",
        name="getString",
        invocation="virtual",
    )
    def get_string(self, key: str, default: str | None) -> str | None:
        return default

    @jvm.native(
        "android/content/SharedPreferences",
        name="getInt",
        invocation="virtual",
    )
    def get_int(self, key: str, default: i32) -> i32:
        return default

    @jvm.native(
        "android/content/SharedPreferences",
        name="getLong",
        invocation="virtual",
    )
    def get_long(self, key: str, default: int) -> int:
        return default

    @jvm.native(
        "android/content/SharedPreferences",
        name="getBoolean",
        invocation="virtual",
    )
    def get_boolean(self, key: str, default: bool) -> bool:
        return default

    @jvm.native(
        "android/content/SharedPreferences",
        name="edit",
        invocation="virtual",
    )
    def edit(self) -> SharedPreferencesEditor:
        return SharedPreferencesEditor()


@jvm.native("android/util/DisplayMetrics")
class DisplayMetrics:
    pass


@jvm.native("android/content/res/Resources")
class Resources:
    @jvm.native(
        "android/content/res/Resources",
        name="getDisplayMetrics",
        invocation="virtual",
    )
    def get_display_metrics(self) -> DisplayMetrics:
        return DisplayMetrics()


@jvm.native("android/util/TypedValue", name="applyDimension")
def _apply_dimension(unit: i32, value: f32, metrics: DisplayMetrics) -> f32:
    return value


@jvm.native("android/content/Context")
class Context:
    def getFilesDir(self) -> File: ...

    def getApplicationContext(self) -> Context: ...

    @jvm.native(
        "android/content/Context",
        name="getSharedPreferences",
        invocation="virtual",
    )
    def get_shared_preferences(self, name: str, mode: i32) -> SharedPreferences:
        return SharedPreferences()

    @jvm.native(
        "android/content/Context",
        name="getPackageName",
        invocation="virtual",
    )
    def get_package_name(self) -> str:
        return ""

    @jvm.native(
        "android/content/Context",
        name="getContentResolver",
        invocation="virtual",
    )
    def get_content_resolver(self) -> ContentResolver:
        return ContentResolver()

    @jvm.native(
        "android/content/Context",
        name="getResources",
        invocation="virtual",
    )
    def get_resources(self) -> Resources:
        return Resources()


def dp(context: Context, value: int) -> i32:
    return i32(
        _apply_dimension(
            i32(1),
            f32(value),
            context.get_resources().get_display_metrics(),
        )
    )


@jvm.native("android/graphics/drawable/Drawable")
class Drawable:
    pass


@jvm.native("android/graphics/drawable/GradientDrawable")
class GradientDrawable(Drawable):
    def __init__(self) -> None:
        self.color = 0
        self.corner_radius = 0.0
        self.stroke_width = 0
        self.stroke_color = 0

    def setColor(self, color: i32) -> None:
        self.color = color

    def setCornerRadius(self, radius: f32) -> None:
        self.corner_radius = radius

    def setStroke(self, width: i32, color: i32) -> None:
        self.stroke_width = width
        self.stroke_color = color


@jvm.native("android/os/Bundle")
class Bundle:
    def __init__(self) -> None:
        pass

    @jvm.native("android/os/Bundle", name="getInt", invocation="virtual")
    def get_int(self, key: str, default: i32) -> i32:
        return default

    @jvm.native("android/os/Bundle", name="putInt", invocation="virtual")
    def put_int(self, key: str, value: i32) -> None:
        pass

    @jvm.native("android/os/Bundle", name="getBoolean", invocation="virtual")
    def get_boolean(self, key: str, default: bool) -> bool:
        return default

    @jvm.native("android/os/Bundle", name="putBoolean", invocation="virtual")
    def put_boolean(self, key: str, value: bool) -> None:
        pass

    @jvm.native("android/os/Bundle", name="getDouble", invocation="virtual")
    def get_double(self, key: str, default: float) -> float:
        return default

    @jvm.native("android/os/Bundle", name="putDouble", invocation="virtual")
    def put_double(self, key: str, value: float) -> None:
        pass

    @jvm.native("android/os/Bundle", name="getString", invocation="virtual")
    def get_string(self, key: str) -> str | None:
        return None

    @jvm.native("android/os/Bundle", name="putString", invocation="virtual")
    def put_string(self, key: str, value: str | None) -> None:
        pass

    @jvm.native("android/os/Bundle", name="getParcelable", invocation="virtual")
    def get_parcelable(self, key: str) -> Parcelable | None:
        return None

    @jvm.native("android/os/Bundle", name="putParcelable", invocation="virtual")
    def put_parcelable(self, key: str, value: Parcelable | None) -> None:
        pass


@jvm.native("android/os/Parcelable")
class Parcelable:
    pass


@jvm.native("java/lang/CharSequence", interface=True)
class JavaCharSequence:
    def __init__(self, value: str = "") -> None:
        self.value = value

    @jvm.native("java/lang/Object", name="toString", invocation="virtual")
    def to_string(self) -> str:
        return self.value

    def length(self) -> i32:
        return i32(len(self.value.encode("utf-16-le", errors="surrogatepass")) // 2)


@jvm.native("android/text/Editable", interface=True)
class Editable(JavaCharSequence):
    pass


@jvm.native("android/text/TextWatcher", interface=True)
class TextWatcher:
    @jvm.native(
        "android/text/TextWatcher",
        name="beforeTextChanged",
        invocation="virtual",
    )
    def before_text_changed(
        self,
        text: JavaCharSequence,
        start: i32,
        count: i32,
        after: i32,
    ) -> None:
        pass

    @jvm.native(
        "android/text/TextWatcher",
        name="onTextChanged",
        invocation="virtual",
    )
    def on_text_changed(
        self,
        text: JavaCharSequence,
        start: i32,
        before: i32,
        count: i32,
    ) -> None:
        pass

    @jvm.native(
        "android/text/TextWatcher",
        name="afterTextChanged",
        invocation="virtual",
    )
    def after_text_changed(self, text: Editable) -> None:
        pass


@jvm.native("android/net/Uri")
class Uri:
    @jvm.native("android/net/Uri", name="toString", invocation="virtual")
    def to_string(self) -> str:
        return ""


@jvm.native("android/content/ContentResolver")
class ContentResolver:
    @jvm.native(
        "android/content/ContentResolver",
        name="takePersistableUriPermission",
        invocation="virtual",
    )
    def take_persistable_uri_permission(self, uri: Uri, flags: i32) -> None:
        pass


@jvm.native("android/content/Intent")
class Intent:
    ACTION_CREATE_DOCUMENT: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "android.intent.action.CREATE_DOCUMENT"
    )
    ACTION_OPEN_DOCUMENT: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "android.intent.action.OPEN_DOCUMENT"
    )
    ACTION_OPEN_DOCUMENT_TREE: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "android.intent.action.OPEN_DOCUMENT_TREE"
    )
    ACTION_SEND: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "android.intent.action.SEND"
    )
    CATEGORY_OPENABLE: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "android.intent.category.OPENABLE"
    )
    EXTRA_TEXT: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "android.intent.extra.TEXT"
    )
    FLAG_ACTIVITY_NEW_TASK: ClassVar[Annotated[i32, jvm.field(writable=False)]] = (
        268435456
    )
    FLAG_GRANT_PERSISTABLE_URI_PERMISSION: ClassVar[
        Annotated[i32, jvm.field(writable=False)]
    ] = 64
    FLAG_GRANT_READ_URI_PERMISSION: ClassVar[
        Annotated[i32, jvm.field(writable=False)]
    ] = 1
    FLAG_GRANT_WRITE_URI_PERMISSION: ClassVar[
        Annotated[i32, jvm.field(writable=False)]
    ] = 2

    def __init__(self) -> None:
        pass

    @jvm.native("android/content/Intent", name="setAction", invocation="virtual")
    def set_action(self, action: str | None) -> Intent:
        return self

    @jvm.native("android/content/Intent", name="setClassName", invocation="virtual")
    def set_class_name(self, package_name: str, class_name: str) -> Intent:
        return self

    @jvm.native("android/content/Intent", name="setData", invocation="virtual")
    def set_data(self, data: Uri | None) -> Intent:
        return self

    @jvm.native("android/content/Intent", name="setType", invocation="virtual")
    def set_type(self, value: str | None) -> Intent:
        return self

    @jvm.native("android/content/Intent", name="addCategory", invocation="virtual")
    def add_category(self, category: str) -> Intent:
        return self

    @jvm.native("android/content/Intent", name="addFlags", invocation="virtual")
    def add_flags(self, flags: i32) -> Intent:
        return self

    @jvm.native("android/content/Intent", name="getAction", invocation="virtual")
    def get_action(self) -> str | None:
        return None

    @jvm.native("android/content/Intent", name="getData", invocation="virtual")
    def get_data(self) -> Uri | None:
        return None

    @jvm.native("android/content/Intent", name="getFlags", invocation="virtual")
    def get_flags(self) -> i32:
        return i32(0)

    @jvm.native("android/content/Intent", name="getIntExtra", invocation="virtual")
    def get_int_extra(self, name: str, default: i32) -> i32:
        return default

    @jvm.native(
        "android/content/Intent",
        name="getIntArrayExtra",
        invocation="virtual",
    )
    def get_int_array_extra(self, name: str) -> JVMArray[i32] | None:
        return None

    @jvm.native("android/content/Intent", name="getStringExtra", invocation="virtual")
    def get_string_extra(self, name: str) -> str | None:
        return None

    @jvm.native("android/content/Intent", name="putExtra", invocation="virtual")
    def put_int_extra(self, name: str, value: i32) -> Intent:
        return self

    @jvm.native("android/content/Intent", name="putExtra", invocation="virtual")
    def put_string_extra(self, name: str, value: str | None) -> Intent:
        return self

    @jvm.native("android/content/Intent", name="putExtra", invocation="virtual")
    def put_int_array_extra(
        self,
        name: str,
        value: JVMArray[i32] | None,
    ) -> Intent:
        return self


@jvm.native("android/content/ComponentName")
class ComponentName:
    def __init__(self, package_name: str, class_name: str) -> None:
        pass

    @jvm.native(
        "android/content/ComponentName",
        name="getPackageName",
        invocation="virtual",
    )
    def get_package_name(self) -> str:
        return ""

    @jvm.native(
        "android/content/ComponentName",
        name="getClassName",
        invocation="virtual",
    )
    def get_class_name(self) -> str:
        return ""


@jvm.native("android/content/BroadcastReceiver")
class BroadcastReceiver:
    def __init__(self) -> None:
        pass

    @jvm.native(
        "android/content/BroadcastReceiver",
        name="onReceive",
        invocation="virtual",
    )
    def on_receive(self, context: Context, intent: Intent) -> None:
        pass


@jvm.native("android/view/View$OnClickListener", interface=True)
class OnClickListener:
    def onClick(self, view: View) -> None:
        pass


@jvm.native("android/view/View")
class View:
    VISIBLE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    INVISIBLE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 4
    GONE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 8

    def __init__(self, context: Context) -> None:
        self.context = context
        self.listener: OnClickListener | None = None

    def setId(self, value: i32) -> None:
        pass

    def setVisibility(self, value: i32) -> None:
        pass

    def setEnabled(self, enabled: bool) -> None:
        pass

    def isEnabled(self) -> bool:
        return True

    def setFocusable(self, focusable: bool) -> None:
        pass

    def setFocusableInTouchMode(self, focusable: bool) -> None:
        pass

    def requestFocus(self) -> bool:
        return True

    def clearFocus(self) -> None:
        pass

    def isFocused(self) -> bool:
        return False

    def setContentDescription(self, value: CharSequence) -> None:
        pass

    def setFitsSystemWindows(self, fit: bool) -> None:
        pass

    def setPadding(
        self,
        left: i32,
        top: i32,
        right: i32,
        bottom: i32,
    ) -> None:
        pass

    def setBackgroundColor(self, color: i32) -> None:
        pass

    def setBackground(self, background: Drawable) -> None:
        pass

    def setElevation(self, elevation: f32) -> None:
        pass

    def setAlpha(self, alpha: f32) -> None:
        pass

    def setMinimumHeight(self, height: i32) -> None:
        pass

    def setMinimumWidth(self, width: i32) -> None:
        pass

    def setLayoutParams(self, params: LayoutParams) -> None:
        pass

    def setOnClickListener(self, listener: OnClickListener) -> None:
        self.listener = listener

    def setOnKeyListener(self, listener: OnKeyListener | None) -> None:
        pass

    def setOnLongClickListener(self, listener: OnLongClickListener | None) -> None:
        pass

    def setOnDragListener(self, listener: OnDragListener | None) -> None:
        pass

    def startDrag(
        self, data: ClipData | None, shadow: DragShadowBuilder,
        local_state: object | None, flags: i32,
    ) -> bool:
        return False

    def getTop(self) -> i32:
        return i32(0)

    def getLeft(self) -> i32:
        return i32(0)

    def getWidth(self) -> i32:
        return i32(0)

    def getRight(self) -> i32: ...

    def getBottom(self) -> i32: ...

    def getTranslationX(self) -> f32: ...

    def getTranslationY(self) -> f32: ...

    def setTranslationX(self, value: f32) -> None: ...

    def setTranslationY(self, value: f32) -> None: ...

    def getLayoutParams(self) -> LayoutParams: ...

    def getVisibility(self) -> i32:
        return self.VISIBLE

    def postDelayed(self, action: Runnable, delay_ms: int) -> bool:
        return False

    def removeCallbacks(self, action: Runnable) -> bool:
        return False

    def getHeight(self) -> i32:
        return i32(0)

    def getScrollY(self) -> i32:
        return i32(0)

    def getContext(self) -> Context:
        return self.context


@jvm.native("android/view/ViewGroup")
class ViewGroup(View):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self.children: list[View] = []

    def addView(self, child: View) -> None:
        self.children.append(child)

    @jvm.native("android/view/ViewGroup", name="addView", invocation="virtual")
    def addViewAt(self, child: View, index: i32) -> None:
        self.children.insert(index, child)

    def removeView(self, child: View) -> None:
        self.children.remove(child)

    def removeViewAt(self, index: i32) -> None:
        self.children.pop(index)

    def removeAllViews(self) -> None:
        self.children.clear()

    def getChildCount(self) -> i32:
        return i32(len(self.children))

    def getChildAt(self, index: i32) -> View:
        return self.children[index]


@jvm.native("android/view/ViewGroup$LayoutParams")
class LayoutParams:
    MATCH_PARENT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = -1
    WRAP_CONTENT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = -2

    def __init__(self, width: i32, height: i32) -> None:
        self.width = width
        self.height = height


@jvm.native("android/view/ViewGroup$MarginLayoutParams")
class MarginLayoutParams(LayoutParams):
    def __init__(self, width: i32, height: i32) -> None:
        super().__init__(width, height)
        self.left_margin = 0
        self.top_margin = 0
        self.right_margin = 0
        self.bottom_margin = 0

    def setMargins(
        self,
        left: i32,
        top: i32,
        right: i32,
        bottom: i32,
    ) -> None:
        self.left_margin = left
        self.top_margin = top
        self.right_margin = right
        self.bottom_margin = bottom


@jvm.native("android/widget/TextView")
class TextView(View):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self.text = ""

    def setText(self, text: CharSequence) -> None:
        self.text = text

    def getText(self) -> JavaCharSequence:
        return JavaCharSequence(self.text)

    def setHint(self, hint: CharSequence) -> None:
        pass

    def setMinLines(self, lines: i32) -> None:
        pass

    def setMaxLines(self, lines: i32) -> None:
        pass

    def setLines(self, lines: i32) -> None:
        pass

    def setSingleLine(self, single_line: bool) -> None:
        pass

    def setInputType(self, input_type: i32) -> None:
        pass

    def setImeOptions(self, options: i32) -> None:
        pass

    def getSelectionStart(self) -> i32:
        return i32(0)

    def getSelectionEnd(self) -> i32:
        return i32(0)

    def getLineCount(self) -> i32:
        return i32(0)

    def setOnEditorActionListener(self, listener: OnEditorActionListener | None) -> None:
        pass

    def addTextChangedListener(self, watcher: TextWatcher) -> None:
        pass

    def removeTextChangedListener(self, watcher: TextWatcher) -> None:
        pass

    def setTextSize(self, size: f32) -> None:
        pass

    def setGravity(self, gravity: i32) -> None:
        pass

    def setTextColor(self, color: i32) -> None:
        pass


@jvm.native("android/view/KeyEvent")
class KeyEvent:
    ACTION_DOWN: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    KEYCODE_ENTER: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 66
    KEYCODE_DEL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 67
    KEYCODE_TAB: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 61

    def getAction(self) -> i32: ...

    def isShiftPressed(self) -> bool: ...


@jvm.native("android/content/ClipData")
class ClipData:
    pass


@jvm.native("android/view/View$DragShadowBuilder")
class DragShadowBuilder:
    def __init__(self, view: View) -> None: ...

    def onProvideShadowMetrics(self, size: Point, touch: Point) -> None: ...


@jvm.native("android/graphics/Point")
class Point:
    x: Annotated[i32, jvm.field()] = 0
    y: Annotated[i32, jvm.field()] = 0

    def __init__(self, x: i32, y: i32) -> None:
        self.x = x
        self.y = y

    def set(self, x: i32, y: i32) -> None:
        self.x = x
        self.y = y


@jvm.native("android/graphics/Rect")
class Rect:
    left: Annotated[i32, jvm.field()] = 0
    top: Annotated[i32, jvm.field()] = 0
    right: Annotated[i32, jvm.field()] = 0
    bottom: Annotated[i32, jvm.field()] = 0

    def __init__(self) -> None: ...


@jvm.native("android/view/DragEvent")
class DragEvent:
    ACTION_DRAG_STARTED: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    ACTION_DRAG_LOCATION: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2
    ACTION_DROP: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 3
    ACTION_DRAG_ENDED: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 4
    ACTION_DRAG_ENTERED: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 5
    ACTION_DRAG_EXITED: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 6

    def getAction(self) -> i32: ...

    def getX(self) -> f32: ...

    def getY(self) -> f32: ...

    def getResult(self) -> bool: ...


@jvm.native("android/view/View$OnLongClickListener", interface=True)
class OnLongClickListener:
    def onLongClick(self, view: View) -> bool: ...


@jvm.native("android/view/View$OnDragListener", interface=True)
class OnDragListener:
    def onDrag(self, view: View, event: DragEvent) -> bool: ...


@jvm.native("android/view/inputmethod/EditorInfo")
class EditorInfo:
    IME_ACTION_NEXT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 5


@jvm.native("android/view/View$OnKeyListener", interface=True)
class OnKeyListener:
    def onKey(self, view: View, key_code: i32, event: KeyEvent) -> bool: ...


@jvm.native("android/widget/TextView$OnEditorActionListener", interface=True)
class OnEditorActionListener:
    def onEditorAction(self, view: TextView, action: i32, event: KeyEvent | None) -> bool: ...


@jvm.native("android/widget/Button")
class Button(TextView):
    pass


@jvm.native("android/widget/LinearLayout")
class LinearLayout(ViewGroup):
    HORIZONTAL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    VERTICAL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1

    def __init__(self, context: Context) -> None:
        super().__init__(context)

    def setOrientation(self, orientation: i32) -> None:
        pass

    def setBaselineAligned(self, aligned: bool) -> None:
        pass

    def setGravity(self, gravity: i32) -> None:
        pass


@jvm.native("android/widget/LinearLayout$LayoutParams")
class LinearLayoutParams(MarginLayoutParams):
    def __init__(self, width: i32, height: i32, weight: f32) -> None:
        super().__init__(width, height)
        self.weight = weight


@jvm.native("android/widget/GridLayout")
class GridLayout(ViewGroup):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    def setRowCount(self, rows: i32) -> None:
        pass

    def setColumnCount(self, columns: i32) -> None:
        pass


@jvm.native("android/view/Gravity")
class Gravity:
    BOTTOM: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 80
    CENTER: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 17
    CENTER_HORIZONTAL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    END: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 8388613
    START: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 8388611
    TOP: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 48


@jvm.native("android/app/Application")
class Application(Context):
    def onCreate(self) -> None: ...


@jvm.native("android/app/Activity")
class Activity(Context):
    RESULT_CANCELED: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    RESULT_OK: ClassVar[Annotated[i32, jvm.field(writable=False)]] = -1

    def __init__(self) -> None:
        self.content: View | None = None

    def onCreate(self, state: Bundle | None) -> None:
        pass

    def onSaveInstanceState(self, state: Bundle) -> None:
        pass

    def onStop(self) -> None:
        pass

    def onDestroy(self) -> None: ...

    def onBackPressed(self) -> None:
        pass

    def setContentView(self, view: View) -> None:
        self.content = view

    def setTitle(self, title: CharSequence) -> None:
        pass

    @jvm.native(
        "android/app/Activity",
        name="startActivityForResult",
        invocation="virtual",
    )
    def start_activity_for_result(self, intent: Intent, request_code: i32) -> None:
        pass

    @jvm.native("android/app/Activity", name="startActivity", invocation="virtual")
    def start_activity(self, intent: Intent) -> None:
        pass

    @jvm.native(
        "android/app/Activity",
        name="onActivityResult",
        invocation="virtual",
    )
    def on_activity_result(
        self,
        request_code: i32,
        result_code: i32,
        data: Intent | None,
    ) -> None:
        pass


@jvm.native("android/graphics/Color", name="parseColor")
def parse_color(value: str) -> i32:
    value = value.removeprefix("#")
    return int(value, 16)


__all__ = [
    "Activity",
    "Application",
    "AndroidAPI",
    "AndroidAvailability",
    "AndroidNullability",
    "BroadcastReceiver",
    "BuildVersion",
    "Bundle",
    "Button",
    "CharSequence",
    "ClipData",
    "ComponentName",
    "ContentResolver",
    "Context",
    "DisplayMetrics",
    "DragEvent",
    "DragShadowBuilder",
    "Drawable",
    "Editable",
    "EditorInfo",
    "GradientDrawable",
    "Gravity",
    "GridLayout",
    "Intent",
    "JavaCharSequence",
    "KeyEvent",
    "LayoutParams",
    "LinearLayout",
    "LinearLayoutParams",
    "MarginLayoutParams",
    "OnClickListener",
    "OnDragListener",
    "OnEditorActionListener",
    "OnKeyListener",
    "OnLongClickListener",
    "Parcelable",
    "Point",
    "Rect",
    "Resources",
    "Runnable",
    "SharedPreferences",
    "SharedPreferencesEditor",
    "TextView",
    "TextWatcher",
    "Uri",
    "View",
    "ViewGroup",
    "dp",
    "parse_color",
]
