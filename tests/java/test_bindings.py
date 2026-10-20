import subprocess

import pytest

from pyjs.android.api import AndroidAPI
from pyjs.android.binding_specs import (
    ANDROID_CONTROL_BINDINGS,
    ANDROID_CONTROL_EXTERNALS,
    APP_WIDGET_BINDINGS,
    APP_WIDGET_EXTERNALS,
)
from pyjs.java import (
    JVMBindingError,
    JVMClass,
    JVMClassBinding,
    JVMExternalClass,
    JVMField,
    JVMFieldBinding,
    JVMMethod,
    JVMMethodBinding,
    JVMParameter,
    JVMUnsupported,
    parse_jvm_method_descriptor,
    read_jvm_class,
    render_jvm_bindings,
    transpile_jvm,
)
from pyjs.tooling.android import AndroidSDK


class Classpath:
    def __init__(self, *classes):
        self.classes = {value.name: value for value in classes}

    def find_class(self, name):
        return self.classes.get(name.replace(".", "/"))


OBJECT = JVMClass("java/lang/Object", 0x0001, None, (), (), ())
WIDGET = JVMClass(
    "sample/Widget",
    0x0001,
    "java/lang/Object",
    (),
    (
        JVMField("ANSWER", "I", 0x0019, constant=42),
        JVMField("label", "Ljava/lang/String;", 0x0001),
    ),
    (
        JVMMethod(
            "<init>",
            "(Ljava/lang/String;)V",
            0x0001,
            (JVMParameter("Ljava/lang/String;", "title"),),
            "V",
        ),
        JVMMethod(
            "render",
            "(IJLjava/lang/CharSequence;)Ljava/lang/String;",
            0x0001,
            (
                JVMParameter("I", "count"),
                JVMParameter("J", "total"),
                JVMParameter("Ljava/lang/CharSequence;", "description"),
            ),
            "Ljava/lang/String;",
        ),
        JVMMethod(
            "render",
            "(I)V",
            0x0001,
            (JVMParameter("I", "count"),),
            "V",
        ),
        JVMMethod("create", "()Lsample/Widget;", 0x0009, (), "Lsample/Widget;"),
    ),
)


def widget_binding(*methods):
    return JVMClassBinding(
        "sample.Widget",
        methods=methods,
        fields=(
            JVMFieldBinding("ANSWER", "I"),
            JVMFieldBinding("label", "Ljava/lang/String;"),
        ),
    )


def test_parses_public_jvm_method_descriptors():
    assert parse_jvm_method_descriptor("(IJLjava/lang/String;)V") == (
        ("I", "J", "Ljava/lang/String;"),
        "V",
    )


def test_renders_selected_members_deterministically():
    source = render_jvm_bindings(
        Classpath(OBJECT, WIDGET),
        (
            widget_binding(
                JVMMethodBinding.constructor("(Ljava/lang/String;)V"),
                JVMMethodBinding(
                    "render",
                    "(IJLjava/lang/CharSequence;)Ljava/lang/String;",
                ),
            ),
        ),
    )

    assert source == '''from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.java import i32
from pyjs.java.primitives import Reference

@jvm.native("java/lang/Object")
class Object:
    pass

@jvm.native("sample/Widget")
class Widget(Object):
    ANSWER: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 42
    label: Annotated[str, jvm.field()]
    def __init__(self, title: str) -> None:
        pass
    def render(
        self,
        count: i32,
        total: int,
        description: Annotated[str, Reference("java/lang/CharSequence")],
    ) -> str:
        pass
'''
    namespace = {}
    exec(source, namespace)
    assert namespace["Widget"].__name__ == "Widget"


def test_generated_binding_round_trips_through_jvm_emission():
    source = render_jvm_bindings(
        Classpath(OBJECT, WIDGET),
        (
            widget_binding(
                JVMMethodBinding.constructor("(Ljava/lang/String;)V"),
                JVMMethodBinding(
                    "render",
                    "(IJLjava/lang/CharSequence;)Ljava/lang/String;",
                ),
            ),
        ),
    )
    source += '''

def main() -> str:
    return Widget("title").render(3, 4, "description")
'''

    compilation = transpile_jvm(source, class_name="generated_bindings")

    assert compilation.main_class == "generated_bindings"
    assert compilation.classes["generated_bindings"].startswith(b"\xca\xfe\xba\xbe")


def test_requires_explicit_python_names_for_selected_overloads():
    with pytest.raises(JVMBindingError, match="duplicated.*python_name"):
        render_jvm_bindings(
            Classpath(OBJECT, WIDGET),
            (
                widget_binding(
                    JVMMethodBinding("render", "(I)V"),
                    JVMMethodBinding(
                        "render",
                        "(IJLjava/lang/CharSequence;)Ljava/lang/String;",
                    ),
                ),
            ),
        )


def test_accepts_explicit_python_names_for_selected_overloads():
    source = render_jvm_bindings(
        Classpath(OBJECT, WIDGET),
        (
            widget_binding(
                JVMMethodBinding("render", "(I)V", "render_count"),
                JVMMethodBinding(
                    "render",
                    "(IJLjava/lang/CharSequence;)Ljava/lang/String;",
                    "render_description",
                ),
            ),
        ),
    )

    assert "def render_count(self, count: i32) -> None:" in source
    assert "def render_description(" in source
    assert source.count('name="render"') == 2


def test_renders_array_bindings():
    array_widget = JVMClass(
        "sample/ArrayWidget",
        0x0001,
        "java/lang/Object",
        (),
        (),
        (
            JVMMethod(
                "values",
                "()[I",
                0x0001,
                (),
                "[I",
            ),
            JVMMethod(
                "fill",
                "([I)[I",
                0x0001,
                (JVMParameter("[I", "values"),),
                "[I",
            ),
            JVMMethod(
                "matrix",
                "()[[I",
                0x0001,
                (),
                "[[I",
            ),
        ),
    )
    source = render_jvm_bindings(
        Classpath(OBJECT, array_widget),
        (
            JVMClassBinding(
                "sample.ArrayWidget",
                methods=(
                    JVMMethodBinding(
                        "values",
                        "()[I",
                        nullable_return=True,
                    ),
                    JVMMethodBinding(
                        "fill",
                        "([I)[I",
                        nullable_return=True,
                        nullable_parameters=(0,),
                    ),
                    JVMMethodBinding("matrix", "()[[I"),
                ),
            ),
        ),
    )

    assert "from pyjs.java import JVMArray, i32" in source
    assert "def values(self) -> JVMArray[i32] | None:" in source
    assert "values: JVMArray[i32] | None" in source
    assert ") -> JVMArray[i32] | None:" in source
    assert "def matrix(self) -> JVMArray[JVMArray[i32]]:" in source


def test_rejects_nullable_primitive_bindings():
    with pytest.raises(
        JVMBindingError,
        match="primitive JVM type.*cannot be nullable",
    ):
        render_jvm_bindings(
            Classpath(OBJECT, WIDGET),
            (
                widget_binding(
                    JVMMethodBinding(
                        "render",
                        "(I)V",
                        nullable_parameters=(0,),
                    ),
                ),
            ),
        )


def test_renders_static_methods_as_native_module_functions():
    source = render_jvm_bindings(
        Classpath(OBJECT, WIDGET),
        (
            JVMClassBinding(
                "sample.Widget",
                methods=(
                    JVMMethodBinding(
                        "create",
                        "()Lsample/Widget;",
                        "create_widget",
                    ),
                ),
            ),
        ),
    )

    assert '''@jvm.native(
    "sample/Widget",
    name="create",
)
def create_widget() -> Widget:
    pass
''' in source
    source += '''

def main() -> int:
    create_widget()
    return 0
'''
    compilation = transpile_jvm(source, class_name="generated_static_binding")
    assert "generated_static_binding" in compilation.classes


def test_reuses_external_native_class_declarations():
    source = render_jvm_bindings(
        Classpath(OBJECT, WIDGET),
        (JVMClassBinding("sample.Widget"),),
        external_classes=(
            JVMExternalClass("java/lang/Object", "builtins", "object"),
        ),
    )

    assert "from builtins import object" in source
    assert "class Widget(object):" in source
    assert '@jvm.native("java/lang/Object")' not in source


def test_rejects_invalid_python_names_and_inaccessible_members():
    with pytest.raises(JVMBindingError, match="not a Python identifier"):
        render_jvm_bindings(
            Classpath(OBJECT, WIDGET),
            (JVMClassBinding("sample.Widget", python_name="not-valid"),),
        )

    private = JVMClass(
        "sample/Private",
        0x0001,
        "java/lang/Object",
        (),
        (JVMField("secret", "I", 0x0002),),
        (),
    )
    with pytest.raises(JVMBindingError, match="not externally accessible"):
        render_jvm_bindings(
            Classpath(OBJECT, private),
            (
                JVMClassBinding(
                    "sample.Private",
                    fields=(JVMFieldBinding("secret", "I"),),
                ),
            ),
        )


def test_installed_android_bindings_round_trip_through_d8(tmp_path):
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 is not installed")

    with api:
        source = api.render_bindings(
            (
                JVMClassBinding(
                    "android/app/Activity",
                    methods=(JVMMethodBinding.constructor("()V"),),
                ),
                JVMClassBinding(
                    "android/view/View$OnClickListener",
                    python_name="OnClickListener",
                    methods=(
                        JVMMethodBinding("onClick", "(Landroid/view/View;)V"),
                    ),
                ),
                JVMClassBinding(
                    "android/view/View",
                    methods=(
                        JVMMethodBinding("setId", "(I)V"),
                        JVMMethodBinding(
                            "setOnClickListener",
                            "(Landroid/view/View$OnClickListener;)V",
                        ),
                    ),
                ),
                JVMClassBinding(
                    "android/widget/TextView",
                    methods=(
                        JVMMethodBinding.constructor(
                            "(Landroid/content/Context;)V"
                        ),
                        JVMMethodBinding(
                            "setText",
                            "(Ljava/lang/CharSequence;)V",
                        ),
                        JVMMethodBinding("setTextSize", "(F)V"),
                    ),
                ),
                JVMClassBinding(
                    "android/graphics/Color",
                    methods=(
                        JVMMethodBinding(
                            "parseColor",
                            "(Ljava/lang/String;)I",
                            "parse_color",
                        ),
                    ),
                ),
            ),
            min_sdk=21,
        )
    source += '''

class Listener(OnClickListener):
    def on_click(self, argument_1: View) -> None:
        argument_1.set_id(8)


def main() -> int:
    view = TextView(Activity())
    view.set_id(7)
    view.set_text("Hello")
    view.set_text_size(16.0)
    view.set_on_click_listener(Listener())
    return parse_color("#ffffff")
'''

    compilation = transpile_jvm(
        source,
        class_name="GeneratedAndroidBindings",
    )

    assert sorted(compilation.classes) == [
        "GeneratedAndroidBindings",
        "GeneratedAndroidBindings$Listener",
    ]
    classes = tmp_path / "classes"
    compilation.write(classes)
    dex = tmp_path / "dex"
    dex.mkdir()
    sdk = AndroidSDK()
    result = subprocess.run(
        [
            sdk.build_tool("d8"),
            "--lib",
            api.android_jar,
            "--min-api",
            "21",
            "--output",
            dex,
            *sorted(classes.rglob("*.class")),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=sdk.environment(),
    )
    assert result.returncode == 0, result.stderr
    assert (dex / "classes.dex").is_file()


def test_android_app_widget_bindings_match_api_35_and_import():
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 is not installed")

    with api:
        source = api.render_bindings(
            APP_WIDGET_BINDINGS,
            external_classes=APP_WIDGET_EXTERNALS,
        )

    namespace = {}
    exec(source, namespace)
    assert "class AppWidgetProvider(BroadcastReceiver):" in source
    assert "app_widget_ids: JVMArray[i32]" in source
    assert "def request_pin_app_widget(" in source
    assert "extras: Bundle | None" in source
    assert "class RemoteViewsFactory(Object):" in source


def test_android_editor_controls_match_api_35_and_import():
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 is not installed")

    with api:
        source = api.render_bindings(
            ANDROID_CONTROL_BINDINGS,
            min_sdk=21,
            external_classes=ANDROID_CONTROL_EXTERNALS,
        )

    namespace = {}
    exec(source, namespace)
    assert "class EditText(TextView):" in source
    assert "def set_selection_range(" in source
    assert "class CheckBox(CompoundButton):" in source
    assert "class OnCheckedChangeListener(Object):" in source
    assert "class ScrollView(FrameLayout):" in source
    assert "TYPE_TEXT_FLAG_MULTI_LINE" in source


def test_recycler_view_bindings_compile_callbacks_and_masonry_layout():
    source = '''
from pyjs.android import Activity, View, ViewGroup
from pyjs.android.recyclerview import (
    ItemTouchCallback,
    ItemTouchHelper,
    RecyclerView,
    RecyclerViewAdapter,
    RecyclerViewViewHolder,
    StaggeredGridLayoutManager,
    StaggeredGridLayoutParams,
    make_movement_flags,
)
from pyjs.java import JVMArray, f32, i32


class Holder(RecyclerViewViewHolder):
    def __init__(self, view: View) -> None:
        super().__init__(view)


class Adapter(RecyclerViewAdapter):
    def on_create_view_holder(
        self,
        parent: ViewGroup,
        view_type: i32,
    ) -> RecyclerViewViewHolder:
        return Holder(parent)

    def on_bind_view_holder(
        self,
        holder: RecyclerViewViewHolder,
        position: i32,
    ) -> None:
        pass

    def get_item_count(self) -> i32:
        return 4

    def get_item_id(self, position: i32) -> int:
        return 1000 + position

    def get_item_view_type(self, position: i32) -> i32:
        return position


class Touch(ItemTouchCallback):
    def is_long_press_drag_enabled(self) -> bool:
        return True

    def get_move_threshold(self, view_holder: RecyclerViewViewHolder) -> f32:
        return 0.35

    def get_movement_flags(
        self,
        recycler_view: RecyclerView,
        view_holder: RecyclerViewViewHolder,
    ) -> i32:
        drag = ItemTouchHelper.UP | ItemTouchHelper.DOWN
        return make_movement_flags(drag, 0)

    def on_move(
        self,
        recycler_view: RecyclerView,
        view_holder: RecyclerViewViewHolder,
        target: RecyclerViewViewHolder,
    ) -> bool:
        return True

    def on_swiped(
        self,
        view_holder: RecyclerViewViewHolder,
        direction: i32,
    ) -> None:
        pass

    def on_selected_changed(
        self,
        view_holder: RecyclerViewViewHolder | None,
        action_state: i32,
    ) -> None:
        pass


def main() -> int:
    view = RecyclerView(Activity())
    layout = StaggeredGridLayoutManager(
        2,
        StaggeredGridLayoutManager.VERTICAL,
    )
    layout.set_gap_strategy(
        StaggeredGridLayoutManager.GAP_HANDLING_MOVE_ITEMS_BETWEEN_SPANS
    )
    layout.scroll_to_position_with_offset(2, 16)
    visible = JVMArray[i32](2)
    layout.find_first_visible_item_positions(visible)
    layout.find_last_visible_item_positions(visible)
    layout.find_first_completely_visible_item_positions(visible)
    layout.find_last_completely_visible_item_positions(visible)
    layout.find_first_visible_item_positions(None)
    header = StaggeredGridLayoutParams(-1, -2)
    header.set_full_span(True)
    assert header.is_full_span()
    header.get_span_index()
    saved = layout.on_save_instance_state()
    layout.on_restore_instance_state(saved)
    view.set_layout_manager(layout)
    adapter = Adapter()
    adapter.set_has_stable_ids(True)
    view.set_adapter(adapter)
    view.scroll_to_position(2)
    ItemTouchHelper(Touch()).attach_to_recycler_view(view)
    return 0
'''

    compilation = transpile_jvm(source, class_name="RecyclerBindings")

    assert sorted(compilation.classes) == [
        "RecyclerBindings",
        "RecyclerBindings$Adapter",
        "RecyclerBindings$Holder",
        "RecyclerBindings$Touch",
        "RecyclerBindings$exception$AssertionError",
        "RecyclerBindings$exception$BaseException",
        "RecyclerBindings$exception$Exception",
        "RecyclerBindings$exception$TypeError",
        "RecyclerBindings$exception$state",
    ]
    adapter = read_jvm_class(compilation.classes["RecyclerBindings$Adapter"])
    assert {
        (method.name, method.descriptor)
        for method in adapter.methods
        if method.name != "<init>"
    } == {
        ("getItemCount", "()I"),
        ("getItemId", "(I)J"),
        ("getItemViewType", "(I)I"),
        (
            "onBindViewHolder",
            "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;I)V",
        ),
        (
            "onCreateViewHolder",
            "(Landroid/view/ViewGroup;I)"
            "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;",
        ),
    }
    touch = read_jvm_class(compilation.classes["RecyclerBindings$Touch"])
    assert {method.name for method in touch.methods} >= {
        "getMoveThreshold",
        "getMovementFlags",
        "isLongPressDragEnabled",
        "onMove",
        "onSwiped",
    }


def test_native_superclass_constructor_must_be_first():
    source = '''
from pyjs.android import Activity, View
from pyjs.android.recyclerview import RecyclerViewViewHolder


class Holder(RecyclerViewViewHolder):
    def __init__(self, view: View) -> None:
        self.ready = True
        super().__init__(view)


def main() -> int:
    Holder(View(Activity()))
    return 0
'''

    with pytest.raises(
        JVMUnsupported,
        match="superclass constructor must be the first",
    ):
        transpile_jvm(source, class_name="InvalidHolder")


def test_native_superclass_requiring_arguments_requires_initializer():
    source = '''
from pyjs.android import Activity, View
from pyjs.android.recyclerview import RecyclerViewViewHolder


class Holder(RecyclerViewViewHolder):
    pass


def main() -> int:
    Holder(View(Activity()))
    return 0
'''

    with pytest.raises(
        JVMUnsupported,
        match="must define an initializer",
    ):
        transpile_jvm(source, class_name="InvalidHolder")
