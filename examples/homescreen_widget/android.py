"""A small notes widget built directly from typed Android APIs."""

from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.android import Activity, BuildVersion, Bundle, Context, Intent, TextView
from pyjs.android.appwidget import (
    AppWidgetManager,
    AppWidgetProvider,
    PendingIntent,
    RemoteViews,
    RemoteViewsFactory,
    RemoteViewsService,
    get_activity_pending_intent,
    get_app_widget_manager,
)
from pyjs.java import JVMArray, i32


@jvm.native("org/pyjs/widgets/R$layout")
class WidgetLayout:
    note_widget_item: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    notes_widget: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0


@jvm.native("org/pyjs/widgets/R$id")
class WidgetId:
    widget_empty: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    widget_item: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    widget_list: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    widget_title: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0


class NotesRemoteViewsFactory(RemoteViewsFactory):
    def __init__(self, package_name: str) -> None:
        self.package_name = package_name

    def on_create(self) -> None:
        pass

    def on_data_set_changed(self) -> None:
        pass

    def on_destroy(self) -> None:
        pass

    def get_count(self) -> i32:
        return i32(3)

    def get_view_at(self, position: i32) -> RemoteViews:
        views = RemoteViews(self.package_name, WidgetLayout.note_widget_item)
        title = "Plan the day"
        if position == 1:
            title = "Review project notes"
        elif position == 2:
            title = "Capture the next idea"
        views.set_text_view_text(WidgetId.widget_item, title)
        fill_in = Intent()
        fill_in.put_int_extra("note_position", position)
        views.set_on_click_fill_in_intent(WidgetId.widget_item, fill_in)
        return views

    def get_loading_view(self) -> RemoteViews | None:
        return None

    def get_view_type_count(self) -> i32:
        return i32(1)

    def get_item_id(self, position: i32) -> int:
        return position

    def has_stable_ids(self) -> bool:
        return True


class NotesRemoteViewsService(RemoteViewsService):
    def on_get_view_factory(self, intent: Intent) -> RemoteViewsFactory:
        return NotesRemoteViewsFactory(self.get_package_name())


class WidgetActivity(Activity):
    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)
        message = TextView(self)
        message.setText("Notes widget opened the app")
        self.setContentView(message)


def widget_pending_intent_flags() -> i32:
    flags = PendingIntent.FLAG_UPDATE_CURRENT
    if BuildVersion.SDK_INT >= 31:
        flags = flags | PendingIntent.FLAG_MUTABLE
    return flags


class NotesWidgetProvider(AppWidgetProvider):
    def on_update(
        self,
        context: Context,
        manager: AppWidgetManager,
        app_widget_ids: JVMArray[i32],
    ) -> None:
        index = 0
        while index < len(app_widget_ids):
            views = RemoteViews(
                context.get_package_name(),
                WidgetLayout.notes_widget,
            )
            views.set_text_view_text(WidgetId.widget_title, "Notes")
            service = Intent()
            service.set_class_name(
                context.get_package_name(),
                "org.pyjs.widgets.PyjsAndroid$NotesRemoteViewsService",
            )
            views.set_remote_adapter(WidgetId.widget_list, service)
            views.set_empty_view(WidgetId.widget_list, WidgetId.widget_empty)
            activity = Intent()
            activity.set_class_name(
                context.get_package_name(),
                "org.pyjs.widgets.PyjsAndroid$WidgetActivity",
            )
            pending = get_activity_pending_intent(
                context,
                app_widget_ids[index],
                activity,
                widget_pending_intent_flags(),
            )
            views.set_pending_intent_template(WidgetId.widget_list, pending)
            manager.update_app_widget(app_widget_ids[index], views)
            index += 1


def main() -> int:
    activity = WidgetActivity()
    activity.onCreate(Bundle())
    NotesWidgetProvider().on_update(
        activity,
        get_app_widget_manager(activity),
        JVMArray[i32](0),
    )
    NotesRemoteViewsService().on_get_view_factory(Intent()).get_count()
    return 0
