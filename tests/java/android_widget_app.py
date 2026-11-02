from pyjs.android import Activity, Bundle
from pyjs.android.appwidget import RemoteViews


class WidgetPreviewActivity(Activity):
    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)
        resources = self.get_resources()
        layout = resources.get_identifier("simple_list_item_1", "layout", "android")
        text = resources.get_identifier("text1", "id", "android")
        assert layout != 0 and text != 0
        assert resources.get_identifier("android:layout/simple_list_item_1", None, None) == layout
        assert resources.get_identifier("missing_pyjs_widget", "layout", "android") == 0
        views = RemoteViews("android", layout)
        views.set_text_view_text(text, "Widget preview 😀")
        self.setContentView(views.apply(self, None))
