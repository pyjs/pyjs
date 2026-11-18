from pyjs.android import (
    Activity,
    Bundle,
    LinearLayout,
    OnClickListener,
    TextView,
    View,
    dp,
)
from pyjs.android.menus import (
    MenuItem,
    OnMenuDismissListener,
    OnMenuItemClickListener,
    PopupMenu,
)
from pyjs.java import i32


class MenuSelection(OnMenuItemClickListener):
    def __init__(self, output: TextView):
        self.output = output

    def onMenuItemClick(self, item: MenuItem) -> bool:
        self.output.setText("Selected " + str(item.get_item_id()))
        return True


class MenuDismissal(OnMenuDismissListener):
    def __init__(self, output: TextView):
        self.output = output

    def onDismiss(self, menu: PopupMenu) -> None:
        self.output.setText("Dismissed")


class OpenMenu(OnClickListener):
    def __init__(self, menu: PopupMenu):
        self.menu = menu

    def onClick(self, view: View) -> None:
        self.menu.show()


class MenuActivity(Activity):
    popup: PopupMenu

    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        root.setPadding(0, dp(self, 96), 0, 0)
        anchor = TextView(self)
        anchor.setId(i32(1001))
        anchor.setText("Actions")
        anchor.setMinimumHeight(i32(100))
        root.addView(anchor)
        selection = TextView(self)
        selection.setId(i32(1002))
        selection.setText("Unchanged")
        root.addView(selection)
        dismissal = TextView(self)
        dismissal.setId(i32(1003))
        root.addView(dismissal)
        self.popup = PopupMenu(self, anchor)
        menu = self.popup.get_menu()
        menu.add(i32(0), i32(10), i32(0), "Bold 雪")
        menu.add(i32(0), i32(20), i32(1), "Unavailable").set_enabled(False)
        menu.add(i32(0), i32(30), i32(2), "Hidden").set_visible(False)
        self.popup.set_on_menu_item_click_listener(MenuSelection(selection))
        self.popup.set_on_dismiss_listener(MenuDismissal(dismissal))
        anchor.setOnClickListener(OpenMenu(self.popup))
        self.setContentView(root)
