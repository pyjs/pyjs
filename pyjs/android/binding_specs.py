"""Demand-driven declarations for the supported AndroidX surface."""

from pyjs.java import (
    JVMClassBinding,
    JVMExternalClass,
    JVMFieldBinding,
    JVMMethodBinding,
)

_method = JVMMethodBinding
_field = JVMFieldBinding

ANDROID_FRAMEWORK_EXTERNALS = (
    JVMExternalClass("android/content/Context", "pyjs.android", "Context"),
    JVMExternalClass("android/view/View", "pyjs.android", "View"),
    JVMExternalClass("android/view/ViewGroup", "pyjs.android", "ViewGroup"),
    JVMExternalClass("android/os/Parcelable", "pyjs.android", "Parcelable"),
    JVMExternalClass(
        "android/view/ViewGroup$MarginLayoutParams",
        "pyjs.android",
        "MarginLayoutParams",
    ),
)

ANDROID_CONTROL_EXTERNALS = (
    JVMExternalClass("android/widget/Button", "pyjs.android", "Button"),
    JVMExternalClass("android/content/Context", "pyjs.android", "Context"),
    JVMExternalClass(
        "android/graphics/drawable/Drawable",
        "pyjs.android",
        "Drawable",
    ),
    JVMExternalClass("android/text/Editable", "pyjs.android", "Editable"),
    JVMExternalClass("android/widget/TextView", "pyjs.android", "TextView"),
    JVMExternalClass("android/view/View", "pyjs.android", "View"),
    JVMExternalClass("android/view/ViewGroup", "pyjs.android", "ViewGroup"),
)

ANDROID_CONTROL_BINDINGS = (
    JVMClassBinding(
        "android/widget/EditText",
        methods=(
            _method.constructor("(Landroid/content/Context;)V"),
            _method("getText", "()Landroid/text/Editable;"),
            _method("setSelection", "(I)V", parameter_names=("index",)),
            _method(
                "setSelection",
                "(II)V",
                "set_selection_range",
                ("start", "stop"),
            ),
            _method("selectAll", "()V"),
        ),
    ),
    JVMClassBinding(
        "android/widget/CompoundButton",
        methods=(
            _method.constructor("(Landroid/content/Context;)V"),
            _method("toggle", "()V"),
            _method("isChecked", "()Z"),
            _method("setChecked", "(Z)V", parameter_names=("checked",)),
            _method(
                "setOnCheckedChangeListener",
                "(Landroid/widget/CompoundButton$OnCheckedChangeListener;)V",
                parameter_names=("listener",),
                nullable_parameters=(0,),
            ),
            _method(
                "setButtonDrawable",
                "(Landroid/graphics/drawable/Drawable;)V",
                parameter_names=("drawable",),
                nullable_parameters=(0,),
            ),
        ),
    ),
    JVMClassBinding(
        "android/widget/CompoundButton$OnCheckedChangeListener",
        python_name="OnCheckedChangeListener",
        methods=(
            _method(
                "onCheckedChanged",
                "(Landroid/widget/CompoundButton;Z)V",
                parameter_names=("button", "checked"),
            ),
        ),
    ),
    JVMClassBinding(
        "android/widget/CheckBox",
        methods=(_method.constructor("(Landroid/content/Context;)V"),),
    ),
    JVMClassBinding(
        "android/widget/ImageView",
        methods=(
            _method.constructor("(Landroid/content/Context;)V"),
            _method("setAdjustViewBounds", "(Z)V"),
            _method("setMaxWidth", "(I)V"),
            _method("setMaxHeight", "(I)V"),
            _method("setImageResource", "(I)V"),
            _method(
                "setImageDrawable",
                "(Landroid/graphics/drawable/Drawable;)V",
                nullable_parameters=(0,),
            ),
            _method("setImageAlpha", "(I)V"),
        ),
    ),
    JVMClassBinding(
        "android/widget/ImageButton",
        methods=(_method.constructor("(Landroid/content/Context;)V"),),
    ),
    JVMClassBinding(
        "android/widget/FrameLayout",
        methods=(
            _method.constructor("(Landroid/content/Context;)V"),
            _method("setForegroundGravity", "(I)V"),
        ),
    ),
    JVMClassBinding(
        "android/widget/ScrollView",
        methods=(
            _method.constructor("(Landroid/content/Context;)V"),
            _method("setFillViewport", "(Z)V"),
            _method(
                "setSmoothScrollingEnabled",
                "(Z)V",
                parameter_names=("enabled",),
            ),
            _method("smoothScrollBy", "(II)V"),
            _method("smoothScrollTo", "(II)V"),
            _method("fling", "(I)V"),
            _method("scrollTo", "(II)V"),
        ),
    ),
    JVMClassBinding(
        "android/text/InputType",
        fields=tuple(
            _field(name, "I")
            for name in (
                "TYPE_CLASS_NUMBER",
                "TYPE_CLASS_TEXT",
                "TYPE_NULL",
                "TYPE_NUMBER_FLAG_DECIMAL",
                "TYPE_NUMBER_FLAG_SIGNED",
                "TYPE_TEXT_FLAG_AUTO_CORRECT",
                "TYPE_TEXT_FLAG_CAP_SENTENCES",
                "TYPE_TEXT_FLAG_MULTI_LINE",
                "TYPE_TEXT_FLAG_NO_SUGGESTIONS",
                "TYPE_TEXT_VARIATION_EMAIL_ADDRESS",
                "TYPE_TEXT_VARIATION_LONG_MESSAGE",
                "TYPE_TEXT_VARIATION_PASSWORD",
                "TYPE_TEXT_VARIATION_URI",
                "TYPE_TEXT_VARIATION_VISIBLE_PASSWORD",
            )
        ),
    ),
)

APP_WIDGET_EXTERNALS = (
    JVMExternalClass(
        "android/content/BroadcastReceiver",
        "pyjs.android",
        "BroadcastReceiver",
    ),
    JVMExternalClass(
        "android/content/ComponentName",
        "pyjs.android",
        "ComponentName",
    ),
    JVMExternalClass("android/content/Context", "pyjs.android", "Context"),
    JVMExternalClass("android/content/Intent", "pyjs.android", "Intent"),
    JVMExternalClass("android/os/Bundle", "pyjs.android", "Bundle"),
)

APP_WIDGET_BINDINGS = (
    JVMClassBinding(
        "android/app/PendingIntent",
        methods=(
            _method(
                "getActivity",
                "(Landroid/content/Context;ILandroid/content/Intent;I)"
                "Landroid/app/PendingIntent;",
                "get_activity_pending_intent",
                ("context", "request_code", "intent", "flags"),
            ),
            _method(
                "getBroadcast",
                "(Landroid/content/Context;ILandroid/content/Intent;I)"
                "Landroid/app/PendingIntent;",
                "get_broadcast_pending_intent",
                ("context", "request_code", "intent", "flags"),
            ),
            _method("cancel", "()V"),
        ),
        fields=(
            _field("FLAG_CANCEL_CURRENT", "I"),
            _field("FLAG_IMMUTABLE", "I"),
            _field("FLAG_MUTABLE", "I"),
            _field("FLAG_NO_CREATE", "I"),
            _field("FLAG_ONE_SHOT", "I"),
            _field("FLAG_UPDATE_CURRENT", "I"),
        ),
    ),
    JVMClassBinding(
        "android/widget/RemoteViews",
        methods=(
            _method.constructor(
                "(Ljava/lang/String;I)V",
                ("package_name", "layout_id"),
            ),
            _method("setViewVisibility", "(II)V"),
            _method("setTextViewText", "(ILjava/lang/CharSequence;)V"),
            _method("setImageViewResource", "(II)V"),
            _method("setContentDescription", "(ILjava/lang/CharSequence;)V"),
            _method(
                "setOnClickPendingIntent",
                "(ILandroid/app/PendingIntent;)V",
            ),
            _method("setRemoteAdapter", "(ILandroid/content/Intent;)V"),
            _method(
                "setPendingIntentTemplate",
                "(ILandroid/app/PendingIntent;)V",
            ),
            _method("setOnClickFillInIntent", "(ILandroid/content/Intent;)V"),
            _method("setEmptyView", "(II)V"),
        ),
    ),
    JVMClassBinding(
        "android/appwidget/AppWidgetManager",
        methods=(
            _method(
                "getInstance",
                "(Landroid/content/Context;)Landroid/appwidget/AppWidgetManager;",
                "get_app_widget_manager",
                ("context",),
            ),
            _method(
                "updateAppWidget",
                "(ILandroid/widget/RemoteViews;)V",
                "update_app_widget",
                ("app_widget_id", "views"),
            ),
            _method(
                "updateAppWidget",
                "([ILandroid/widget/RemoteViews;)V",
                "update_app_widgets",
                ("app_widget_ids", "views"),
            ),
            _method(
                "updateAppWidget",
                "(Landroid/content/ComponentName;Landroid/widget/RemoteViews;)V",
                "update_component_widgets",
                ("provider", "views"),
            ),
            _method(
                "partiallyUpdateAppWidget",
                "(ILandroid/widget/RemoteViews;)V",
                "partially_update_app_widget",
                ("app_widget_id", "views"),
            ),
            _method(
                "getAppWidgetIds",
                "(Landroid/content/ComponentName;)[I",
                parameter_names=("provider",),
            ),
            _method(
                "getAppWidgetOptions",
                "(I)Landroid/os/Bundle;",
                parameter_names=("app_widget_id",),
            ),
            _method(
                "notifyAppWidgetViewDataChanged",
                "(II)V",
                parameter_names=("app_widget_id", "view_id"),
            ),
            _method("isRequestPinAppWidgetSupported", "()Z"),
            _method(
                "requestPinAppWidget",
                "(Landroid/content/ComponentName;Landroid/os/Bundle;"
                "Landroid/app/PendingIntent;)Z",
                parameter_names=("provider", "extras", "success_callback"),
            ),
        ),
        fields=tuple(
            _field(name, descriptor)
            for name, descriptor in (
                ("ACTION_APPWIDGET_UPDATE", "Ljava/lang/String;"),
                ("EXTRA_APPWIDGET_ID", "Ljava/lang/String;"),
                ("EXTRA_APPWIDGET_IDS", "Ljava/lang/String;"),
                ("INVALID_APPWIDGET_ID", "I"),
                ("OPTION_APPWIDGET_MAX_HEIGHT", "Ljava/lang/String;"),
                ("OPTION_APPWIDGET_MAX_WIDTH", "Ljava/lang/String;"),
                ("OPTION_APPWIDGET_MIN_HEIGHT", "Ljava/lang/String;"),
                ("OPTION_APPWIDGET_MIN_WIDTH", "Ljava/lang/String;"),
            )
        ),
    ),
    JVMClassBinding(
        "android/appwidget/AppWidgetProvider",
        methods=(
            _method.constructor("()V"),
            _method(
                "onUpdate",
                "(Landroid/content/Context;Landroid/appwidget/AppWidgetManager;[I)V",
                parameter_names=("context", "manager", "app_widget_ids"),
            ),
            _method(
                "onAppWidgetOptionsChanged",
                "(Landroid/content/Context;Landroid/appwidget/AppWidgetManager;"
                "ILandroid/os/Bundle;)V",
                parameter_names=("context", "manager", "app_widget_id", "options"),
            ),
            _method(
                "onDeleted",
                "(Landroid/content/Context;[I)V",
                parameter_names=("context", "app_widget_ids"),
            ),
            _method("onEnabled", "(Landroid/content/Context;)V"),
            _method("onDisabled", "(Landroid/content/Context;)V"),
        ),
    ),
    JVMClassBinding(
        "android/widget/RemoteViewsService",
        methods=(
            _method.constructor("()V"),
            _method(
                "onGetViewFactory",
                "(Landroid/content/Intent;)"
                "Landroid/widget/RemoteViewsService$RemoteViewsFactory;",
                parameter_names=("intent",),
            ),
        ),
    ),
    JVMClassBinding(
        "android/widget/RemoteViewsService$RemoteViewsFactory",
        python_name="RemoteViewsFactory",
        methods=(
            _method("onCreate", "()V"),
            _method("onDataSetChanged", "()V"),
            _method("onDestroy", "()V"),
            _method("getCount", "()I"),
            _method(
                "getViewAt",
                "(I)Landroid/widget/RemoteViews;",
                parameter_names=("position",),
            ),
            _method(
                "getLoadingView",
                "()Landroid/widget/RemoteViews;",
                nullable_return=True,
            ),
            _method("getViewTypeCount", "()I"),
            _method("getItemId", "(I)J", parameter_names=("position",)),
            _method("hasStableIds", "()Z"),
        ),
    ),
)

RECYCLER_VIEW_BINDINGS = (
    JVMClassBinding(
        "androidx/recyclerview/widget/RecyclerView",
        methods=(
            _method.constructor("(Landroid/content/Context;)V"),
            _method(
                "setAdapter",
                "(Landroidx/recyclerview/widget/RecyclerView$Adapter;)V",
            ),
            _method(
                "setLayoutManager",
                "(Landroidx/recyclerview/widget/RecyclerView$LayoutManager;)V",
            ),
            _method("setHasFixedSize", "(Z)V"),
            _method("scrollToPosition", "(I)V"),
            _method("smoothScrollToPosition", "(I)V"),
            _method("suppressLayout", "(Z)V"),
        ),
    ),
    JVMClassBinding(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        python_name="RecyclerViewAdapter",
        methods=(
            _method.constructor("()V"),
            _method(
                "onCreateViewHolder",
                "(Landroid/view/ViewGroup;I)"
                "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;",
                parameter_names=("parent", "view_type"),
            ),
            _method(
                "onBindViewHolder",
                "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;I)V",
                parameter_names=("holder", "position"),
            ),
            _method("getItemCount", "()I"),
            _method("getItemId", "(I)J"),
            _method("getItemViewType", "(I)I"),
            _method("setHasStableIds", "(Z)V"),
            _method("hasStableIds", "()Z"),
            _method("notifyItemChanged", "(I)V"),
            _method("notifyItemMoved", "(II)V"),
            _method("notifyItemInserted", "(I)V"),
            _method("notifyItemRemoved", "(I)V"),
            _method("notifyItemRangeChanged", "(II)V"),
            _method("notifyItemRangeInserted", "(II)V"),
            _method("notifyItemRangeRemoved", "(II)V"),
            _method("notifyDataSetChanged", "()V"),
        ),
    ),
    JVMClassBinding(
        "androidx/recyclerview/widget/RecyclerView$ViewHolder",
        python_name="RecyclerViewViewHolder",
        fields=(
            _field("itemView", "Landroid/view/View;"),
        ),
        methods=(
            _method.constructor("(Landroid/view/View;)V"),
            _method("getAbsoluteAdapterPosition", "()I"),
            _method("getBindingAdapterPosition", "()I"),
            _method("getItemId", "()J"),
            _method("getLayoutPosition", "()I"),
            _method("getOldPosition", "()I"),
        ),
    ),
    JVMClassBinding(
        "androidx/recyclerview/widget/RecyclerView$LayoutManager",
        python_name="RecyclerViewLayoutManager",
    ),
    JVMClassBinding(
        "androidx/recyclerview/widget/RecyclerView$LayoutParams",
        python_name="RecyclerViewLayoutParams",
        methods=(_method.constructor("(II)V"),),
    ),
    JVMClassBinding(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        methods=(
            _method.constructor("(II)V"),
            _method("getGapStrategy", "()I"),
            _method("getReverseLayout", "()Z"),
            _method("getSpanCount", "()I"),
            _method(
                "findFirstVisibleItemPositions",
                "([I)[I",
                nullable_parameters=(0,),
            ),
            _method(
                "findLastVisibleItemPositions",
                "([I)[I",
                nullable_parameters=(0,),
            ),
            _method(
                "findFirstCompletelyVisibleItemPositions",
                "([I)[I",
                nullable_parameters=(0,),
            ),
            _method(
                "findLastCompletelyVisibleItemPositions",
                "([I)[I",
                nullable_parameters=(0,),
            ),
            _method(
                "onSaveInstanceState",
                "()Landroid/os/Parcelable;",
                nullable_return=True,
            ),
            _method(
                "onRestoreInstanceState",
                "(Landroid/os/Parcelable;)V",
                nullable_parameters=(0,),
            ),
            _method("invalidateSpanAssignments", "()V"),
            _method("scrollToPositionWithOffset", "(II)V"),
            _method("setGapStrategy", "(I)V"),
            _method("setReverseLayout", "(Z)V"),
            _method("setSpanCount", "(I)V"),
        ),
        fields=(
            _field("GAP_HANDLING_NONE", "I"),
            _field("GAP_HANDLING_LAZY", "I"),
            _field("GAP_HANDLING_MOVE_ITEMS_BETWEEN_SPANS", "I"),
            _field("HORIZONTAL", "I"),
            _field("VERTICAL", "I"),
        ),
    ),
    JVMClassBinding(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager$LayoutParams",
        python_name="StaggeredGridLayoutParams",
        methods=(
            _method.constructor("(II)V"),
            _method("setFullSpan", "(Z)V"),
            _method("isFullSpan", "()Z"),
            _method("getSpanIndex", "()I"),
        ),
        fields=(_field("INVALID_SPAN_ID", "I"),),
    ),
    JVMClassBinding(
        "androidx/recyclerview/widget/ItemTouchHelper",
        methods=(
            _method.constructor(
                "(Landroidx/recyclerview/widget/ItemTouchHelper$Callback;)V"
            ),
            _method(
                "attachToRecyclerView",
                "(Landroidx/recyclerview/widget/RecyclerView;)V",
                nullable_parameters=(0,),
            ),
            _method(
                "startDrag",
                "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;)V",
            ),
        ),
        fields=(
            _field("ACTION_STATE_DRAG", "I"),
            _field("ACTION_STATE_IDLE", "I"),
            _field("ACTION_STATE_SWIPE", "I"),
            _field("UP", "I"),
            _field("DOWN", "I"),
            _field("START", "I"),
            _field("END", "I"),
            _field("LEFT", "I"),
            _field("RIGHT", "I"),
        ),
    ),
    JVMClassBinding(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        python_name="ItemTouchCallback",
        methods=(
            _method.constructor("()V"),
            _method(
                "makeMovementFlags",
                "(II)I",
                "make_movement_flags",
            ),
            _method(
                "getMovementFlags",
                "(Landroidx/recyclerview/widget/RecyclerView;"
                "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;)I",
                parameter_names=("recycler_view", "view_holder"),
            ),
            _method(
                "onMove",
                "(Landroidx/recyclerview/widget/RecyclerView;"
                "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;"
                "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;)Z",
                parameter_names=("recycler_view", "view_holder", "target"),
            ),
            _method(
                "onSwiped",
                "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;I)V",
                parameter_names=("view_holder", "direction"),
            ),
            _method(
                "onSelectedChanged",
                "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;I)V",
                parameter_names=("view_holder", "action_state"),
                nullable_parameters=(0,),
            ),
            _method("isLongPressDragEnabled", "()Z"),
            _method("isItemViewSwipeEnabled", "()Z"),
            _method(
                "getMoveThreshold",
                "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;)F",
                parameter_names=("view_holder",),
            ),
            _method(
                "getSwipeThreshold",
                "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;)F",
                parameter_names=("view_holder",),
            ),
            _method(
                "canDropOver",
                "(Landroidx/recyclerview/widget/RecyclerView;"
                "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;"
                "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;)Z",
                parameter_names=("recycler_view", "current", "target"),
            ),
            _method(
                "clearView",
                "(Landroidx/recyclerview/widget/RecyclerView;"
                "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;)V",
                parameter_names=("recycler_view", "view_holder"),
            ),
        ),
    ),
)

__all__ = [
    "ANDROID_CONTROL_BINDINGS",
    "ANDROID_CONTROL_EXTERNALS",
    "ANDROID_FRAMEWORK_EXTERNALS",
    "APP_WIDGET_BINDINGS",
    "APP_WIDGET_EXTERNALS",
    "RECYCLER_VIEW_BINDINGS",
]
