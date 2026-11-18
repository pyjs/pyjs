"""Anchored platform menus and their native selection callbacks."""

from pyjs import jvm
from pyjs.android import CharSequence, Context, View
from pyjs.java import i32


@jvm.native("android/view/MenuItem", interface=True)
class MenuItem:
    @jvm.native("android/view/MenuItem", name="getItemId", invocation="virtual")
    def get_item_id(self) -> i32: ...

    @jvm.native("android/view/MenuItem", name="setEnabled", invocation="virtual")
    def set_enabled(self, enabled: bool) -> MenuItem: ...

    @jvm.native("android/view/MenuItem", name="isEnabled", invocation="virtual")
    def is_enabled(self) -> bool: ...

    @jvm.native("android/view/MenuItem", name="setVisible", invocation="virtual")
    def set_visible(self, visible: bool) -> MenuItem: ...

    @jvm.native("android/view/MenuItem", name="isVisible", invocation="virtual")
    def is_visible(self) -> bool: ...


@jvm.native("android/view/Menu", interface=True)
class Menu:
    def add(self, group_id: i32, item_id: i32, order: i32, title: CharSequence) -> MenuItem: ...

    @jvm.native("android/view/Menu", name="findItem", invocation="virtual")
    def find_item(self, item_id: i32) -> MenuItem | None: ...

    @jvm.native("android/view/Menu", name="removeItem", invocation="virtual")
    def remove_item(self, item_id: i32) -> None: ...

    def clear(self) -> None: ...


@jvm.native("android/widget/PopupMenu$OnMenuItemClickListener", interface=True)
class OnMenuItemClickListener:
    def onMenuItemClick(self, item: MenuItem) -> bool: ...


@jvm.native("android/widget/PopupMenu$OnDismissListener", interface=True)
class OnMenuDismissListener:
    def onDismiss(self, menu: PopupMenu) -> None: ...


@jvm.native("android/widget/PopupMenu")
class PopupMenu:
    def __init__(self, context: Context, anchor: View) -> None: ...

    @jvm.native("android/widget/PopupMenu", name="getMenu", invocation="virtual")
    def get_menu(self) -> Menu: ...

    @jvm.native("android/widget/PopupMenu", name="setOnMenuItemClickListener", invocation="virtual")
    def set_on_menu_item_click_listener(self, listener: OnMenuItemClickListener | None) -> None: ...

    @jvm.native("android/widget/PopupMenu", name="setOnDismissListener", invocation="virtual")
    def set_on_dismiss_listener(self, listener: OnMenuDismissListener | None) -> None: ...

    def show(self) -> None: ...

    def dismiss(self) -> None: ...
