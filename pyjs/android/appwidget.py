"""Generated Android home-screen widget declarations."""

from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.android import BroadcastReceiver, Bundle, ComponentName, Context, Intent
from pyjs.java import JVMArray, i32
from pyjs.java.primitives import Reference


@jvm.native("java/lang/Object")
class Object:
    pass


@jvm.native("android/app/PendingIntent")
class PendingIntent(Object):
    FLAG_CANCEL_CURRENT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 268435456
    FLAG_IMMUTABLE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 67108864
    FLAG_MUTABLE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 33554432
    FLAG_NO_CREATE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 536870912
    FLAG_ONE_SHOT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1073741824
    FLAG_UPDATE_CURRENT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 134217728

    def cancel(self) -> None:
        pass


@jvm.native("android/content/ContextWrapper")
class ContextWrapper(Context):
    pass


@jvm.native("android/app/Service")
class Service(ContextWrapper):
    pass


@jvm.native("android/appwidget/AppWidgetManager")
class AppWidgetManager(Object):
    ACTION_APPWIDGET_UPDATE: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "android.appwidget.action.APPWIDGET_UPDATE"
    )
    EXTRA_APPWIDGET_ID: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "appWidgetId"
    )
    EXTRA_APPWIDGET_IDS: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "appWidgetIds"
    )
    INVALID_APPWIDGET_ID: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    OPTION_APPWIDGET_MAX_HEIGHT: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "appWidgetMaxHeight"
    )
    OPTION_APPWIDGET_MAX_WIDTH: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "appWidgetMaxWidth"
    )
    OPTION_APPWIDGET_MIN_HEIGHT: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "appWidgetMinHeight"
    )
    OPTION_APPWIDGET_MIN_WIDTH: ClassVar[Annotated[str, jvm.field(writable=False)]] = (
        "appWidgetMinWidth"
    )

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="updateAppWidget",
        invocation="virtual",
    )
    def update_app_widget(self, app_widget_id: i32, views: RemoteViews) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="updateAppWidget",
        invocation="virtual",
    )
    def update_app_widgets(
        self,
        app_widget_ids: JVMArray[i32],
        views: RemoteViews,
    ) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="updateAppWidget",
        invocation="virtual",
    )
    def update_component_widgets(
        self,
        provider: ComponentName,
        views: RemoteViews,
    ) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="partiallyUpdateAppWidget",
        invocation="virtual",
    )
    def partially_update_app_widget(
        self,
        app_widget_id: i32,
        views: RemoteViews,
    ) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="getAppWidgetIds",
        invocation="virtual",
    )
    def get_app_widget_ids(self, provider: ComponentName) -> JVMArray[i32]:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="getAppWidgetOptions",
        invocation="virtual",
    )
    def get_app_widget_options(self, app_widget_id: i32) -> Bundle:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="notifyAppWidgetViewDataChanged",
        invocation="virtual",
    )
    def notify_app_widget_view_data_changed(
        self,
        app_widget_id: i32,
        view_id: i32,
    ) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="isRequestPinAppWidgetSupported",
        invocation="virtual",
    )
    def is_request_pin_app_widget_supported(self) -> bool:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetManager",
        name="requestPinAppWidget",
        invocation="virtual",
    )
    def request_pin_app_widget(
        self,
        provider: ComponentName,
        extras: Bundle | None,
        success_callback: PendingIntent | None,
    ) -> bool:
        pass


@jvm.native("android/appwidget/AppWidgetProvider")
class AppWidgetProvider(BroadcastReceiver):
    def __init__(self) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetProvider",
        name="onUpdate",
        invocation="virtual",
    )
    def on_update(
        self,
        context: Context,
        manager: AppWidgetManager,
        app_widget_ids: JVMArray[i32],
    ) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetProvider",
        name="onAppWidgetOptionsChanged",
        invocation="virtual",
    )
    def on_app_widget_options_changed(
        self,
        context: Context,
        manager: AppWidgetManager,
        app_widget_id: i32,
        options: Bundle,
    ) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetProvider",
        name="onDeleted",
        invocation="virtual",
    )
    def on_deleted(self, context: Context, app_widget_ids: JVMArray[i32]) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetProvider",
        name="onEnabled",
        invocation="virtual",
    )
    def on_enabled(self, context: Context) -> None:
        pass

    @jvm.native(
        "android/appwidget/AppWidgetProvider",
        name="onDisabled",
        invocation="virtual",
    )
    def on_disabled(self, context: Context) -> None:
        pass


@jvm.native("android/widget/RemoteViews")
class RemoteViews(Object):
    def __init__(self, package_name: str, layout_id: i32) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setViewVisibility",
        invocation="virtual",
    )
    def set_view_visibility(self, view_id: i32, visibility: i32) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setTextViewText",
        invocation="virtual",
    )
    def set_text_view_text(
        self,
        view_id: i32,
        text: Annotated[str, Reference("java/lang/CharSequence")],
    ) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setImageViewResource",
        invocation="virtual",
    )
    def set_image_view_resource(self, view_id: i32, src_id: i32) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setContentDescription",
        invocation="virtual",
    )
    def set_content_description(
        self,
        view_id: i32,
        content_description: Annotated[str, Reference("java/lang/CharSequence")],
    ) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setOnClickPendingIntent",
        invocation="virtual",
    )
    def set_on_click_pending_intent(
        self,
        view_id: i32,
        pending_intent: PendingIntent,
    ) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setRemoteAdapter",
        invocation="virtual",
    )
    def set_remote_adapter(self, view_id: i32, intent: Intent) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setPendingIntentTemplate",
        invocation="virtual",
    )
    def set_pending_intent_template(
        self,
        view_id: i32,
        pending_intent_template: PendingIntent,
    ) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setOnClickFillInIntent",
        invocation="virtual",
    )
    def set_on_click_fill_in_intent(self, view_id: i32, fill_in_intent: Intent) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViews",
        name="setEmptyView",
        invocation="virtual",
    )
    def set_empty_view(self, view_id: i32, empty_view_id: i32) -> None:
        pass


@jvm.native("android/widget/RemoteViewsService")
class RemoteViewsService(Service):
    def __init__(self) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService",
        name="onGetViewFactory",
        invocation="virtual",
    )
    def on_get_view_factory(self, intent: Intent) -> RemoteViewsFactory:
        pass


@jvm.native("android/widget/RemoteViewsService$RemoteViewsFactory", interface=True)
class RemoteViewsFactory(Object):
    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="onCreate",
        invocation="virtual",
    )
    def on_create(self) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="onDataSetChanged",
        invocation="virtual",
    )
    def on_data_set_changed(self) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="onDestroy",
        invocation="virtual",
    )
    def on_destroy(self) -> None:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="getCount",
        invocation="virtual",
    )
    def get_count(self) -> i32:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="getViewAt",
        invocation="virtual",
    )
    def get_view_at(self, position: i32) -> RemoteViews:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="getLoadingView",
        invocation="virtual",
    )
    def get_loading_view(self) -> RemoteViews | None:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="getViewTypeCount",
        invocation="virtual",
    )
    def get_view_type_count(self) -> i32:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="getItemId",
        invocation="virtual",
    )
    def get_item_id(self, position: i32) -> int:
        pass

    @jvm.native(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        name="hasStableIds",
        invocation="virtual",
    )
    def has_stable_ids(self) -> bool:
        pass


@jvm.native(
    "android/app/PendingIntent",
    name="getActivity",
)
def get_activity_pending_intent(
    context: Context,
    request_code: i32,
    intent: Intent,
    flags: i32,
) -> PendingIntent:
    pass


@jvm.native(
    "android/app/PendingIntent",
    name="getBroadcast",
)
def get_broadcast_pending_intent(
    context: Context,
    request_code: i32,
    intent: Intent,
    flags: i32,
) -> PendingIntent:
    pass


@jvm.native(
    "android/appwidget/AppWidgetManager",
    name="getInstance",
)
def get_app_widget_manager(context: Context) -> AppWidgetManager:
    pass


__all__ = [
    "AppWidgetManager",
    "AppWidgetProvider",
    "PendingIntent",
    "RemoteViews",
    "RemoteViewsFactory",
    "RemoteViewsService",
    "get_activity_pending_intent",
    "get_app_widget_manager",
    "get_broadcast_pending_intent",
]
