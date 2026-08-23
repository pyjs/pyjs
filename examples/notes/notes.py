from pathlib import Path

from pyjs import JS, js
from pyjs.nativescript import (
    AndroidActivityBackPressedEventData,
    Application,
    Button,
    EventData,
    GridLayout,
    Label,
    Page,
    ScrollView,
    StackLayout,
    TextField,
    TextView,
    View,
)
from pyjs.nativescript.masonry import MasonryLayout
from pyjs.nativescript.masonry_reorder import (
    MasonryReorderController,
    MasonryReorderResult,
)
from pyjs.tooling.nativescript import NativeScriptProject

APP_ASSETS = Path(__file__).parent / "mobile_assets"
MATERIAL_FONT: JS = "MaterialIcons-Regular"
ICON_ADD: JS = "\ue145"
ICON_ARCHIVE: JS = "\ue149"
ICON_BACK: JS = "\ue5c4"
ICON_CHECKED: JS = "\ue834"
ICON_CHECKBOX: JS = "\ue835"
ICON_CLOSE: JS = "\ue5cd"
ICON_DELETE: JS = "\ue872"
ICON_GRID: JS = "\ue9b0"
ICON_LIST: JS = "\ue8e9"
ICON_MENU: JS = "\ue5d2"
ICON_MORE: JS = "\ue5d4"
ICON_NOTES: JS = "\ue0f0"
ICON_PALETTE: JS = "\ue40a"
ICON_PIN: JS = "\uf10d"


@js
class ChecklistItem:
    def __init__(self, item_id: str, text: str, checked: bool = False):
        self.id = item_id
        self.text = text
        self.checked = checked


@js
class Note:
    def __init__(
        self,
        note_id: str,
        title: str,
        body: str = "",
        color: str = "#ffffff",
        pinned: bool = False,
        items: list[ChecklistItem] | None = None,
        archived: bool = False,
        trashed: bool = False,
        grid_column: int = -1,
        grid_column_count: int = 0,
    ):
        self.id = note_id
        self.title = title
        self.body = body
        self.color = color
        self.pinned = pinned
        self.items: list[ChecklistItem] = []
        if items is not None:
            self.items = items
        self.archived = archived
        self.trashed = trashed
        self.grid_column = grid_column
        self.grid_column_count = grid_column_count

    def is_checklist(self) -> bool:
        return len(self.items) > 0


@js
def sample_notes() -> list[Note]:
    return [
        Note(
            "launch",
            "Launch checklist",
            color="#fff475",
            pinned=True,
            items=[
                ChecklistItem("review", "Review the final build", True),
                ChecklistItem("screens", "Capture store screenshots"),
                ChecklistItem("release", "Publish the release notes"),
            ],
        ),
        Note(
            "weekend",
            "Weekend ideas",
            "Walk the river trail\nTry the new bakery\nCall Maya",
            "#cbf0f8",
            True,
        ),
        Note(
            "groceries",
            "Groceries",
            color="#ccff90",
            items=[
                ChecklistItem("coffee", "Coffee beans"),
                ChecklistItem("lemons", "Lemons"),
                ChecklistItem("bread", "Sourdough bread", True),
                ChecklistItem("basil", "Fresh basil"),
            ],
        ),
        Note(
            "design",
            "Design notes",
            "Keep the hierarchy quiet. Let spacing, color, and typography do "
            "the work before adding another border.",
            "#ffffff",
        ),
        Note(
            "reading",
            "Reading list",
            color="#d7aefb",
            items=[
                ChecklistItem("design-systems", "Design Systems"),
                ChecklistItem("shape", "The Shape of Design"),
                ChecklistItem("everyday", "The Design of Everyday Things"),
            ],
        ),
        Note(
            "recipe",
            "Pasta night",
            "Tomatoes, garlic, olive oil, chili, basil, and plenty of parmesan.",
            "#f28b82",
        ),
        Note(
            "quote",
            "A useful reminder",
            "Make it work, make it clear, then make it delightful.",
            "#e8eaed",
        ),
        Note(
            "archive-demo",
            "Trip packing list",
            "Passport\nHeadphones\nNotebook",
            "#cbf0f8",
            archived=True,
        ),
        Note(
            "trash-demo",
            "Old draft",
            "This sample note demonstrates the trash view.",
            trashed=True,
        ),
    ]


@js
class NotesApp:
    def __init__(self, notes: list[Note] | None = None):
        self.notes = sample_notes()
        if notes is not None:
            self.notes = notes
        self.view = "notes"
        self.query = ""
        self.layout_mode = "grid"
        self.editing_id = ""
        self.creation_menu_visible = False
        self.navigation_drawer_visible = False
        self.palette_visible = False
        self.action_sheet_visible = False
        self.sequence = len(self.notes) + 1
        self.root = GridLayout()
        self.root.id = "notes-root"
        self.root.testID = "notes-root"
        self.list_content = GridLayout()
        self.note_reorder: MasonryReorderController | None = None
        self.page_view = Page()
        self.page_view.actionBarHidden = True
        self.page_view.statusBarStyle = "dark"
        self.page_view.className = "bg-white text-slate-900"
        self.page_view.content = self.root
        Application.android.on(
            Application.android.activityBackPressedEvent,
            self.android_back_pressed,
        )
        self.render()

    def label(self, text: str, test_id: str, class_name: str) -> Label:
        label = Label()
        label.id = test_id
        label.testID = test_id
        label.text = text
        label.textWrap = True
        label.className = class_name
        return label

    def button(self, text: str, test_id: str, class_name: str) -> Button:
        button = Button()
        button.id = test_id
        button.testID = test_id
        button.text = text
        button.className = class_name
        button.androidElevation = 0
        button.androidDynamicElevationOffset = 0
        button.textTransform = "none"
        button.accessible = True
        button.accessibilityLabel = text
        button.accessibilityRole = "button"
        return button

    def icon_button(
        self,
        icon: str,
        test_id: str,
        accessibility_label: str,
        size: int = 24,
    ) -> Button:
        button = self.button(icon, test_id, "bg-transparent text-slate-700")
        button.fontFamily = MATERIAL_FONT
        button.fontSize = size
        button.accessibilityLabel = accessibility_label
        return button

    def note(self, note_id: str) -> Note | None:
        for note in self.notes:
            if note.id == note_id:
                return note
        return None

    def current_note(self) -> Note | None:
        return self.note(self.editing_id)

    def visible_notes(self) -> list[Note]:
        query = self.query.strip().lower()
        visible: list[Note] = []
        for note in self.notes:
            in_view = False
            if self.view == "notes":
                in_view = not note.archived and not note.trashed
            elif self.view == "archive":
                in_view = note.archived and not note.trashed
            elif self.view == "trash":
                in_view = note.trashed
            if not in_view:
                continue
            searchable = note.title + " " + note.body
            for item in note.items:
                searchable += " " + item.text
            if query == "" or query in searchable.lower():
                visible.append(note)
        visible.sort(key=lambda note: 0 if note.pinned else 1)
        return visible

    def note_preview(self, note: Note) -> str:
        if not note.is_checklist():
            return note.body
        lines: list[str] = []
        for item in note.items:
            lines.append(("✓ " if item.checked else "□ ") + item.text)
        return "\n".join(lines)

    def checklist_preview(self, note: Note) -> StackLayout:
        preview = StackLayout()
        preview.id = "note-preview-" + note.id
        preview.testID = preview.id
        preview.marginTop = 4
        for index in range(len(note.items)):
            item = note.items[index]
            row = GridLayout()
            row.columns = "20,*"
            row.marginBottom = 2
            marker = self.label(
                ICON_CHECKED if item.checked else ICON_CHECKBOX,
                "preview-marker-" + note.id + "-" + str(index),
                "text-slate-600",
            )
            marker.column = 0
            marker.fontFamily = MATERIAL_FONT
            marker.fontSize = 16
            marker.verticalAlignment = "top"
            marker.accessible = False
            row.addChild(marker)
            text = self.label(
                item.text,
                "preview-item-" + note.id + "-" + str(index),
                "text-sm text-slate-500 line-through" if item.checked else "text-sm text-slate-700",
            )
            text.column = 1
            text.fontSize = 14
            text.verticalAlignment = "top"
            row.addChild(text)
            preview.addChild(row)
        return preview

    def note_card(self, note: Note) -> StackLayout:
        card = StackLayout()
        card.id = note.id
        card.testID = "note-card-" + note.id
        card.className = "m-1 rounded-lg border bg-white p-3"
        card.backgroundColor = note.color
        card.borderColor = "#dadce0"
        card.borderWidth = 1
        card.borderRadius = 8
        card.accessible = True
        card.accessibilityLabel = note.title
        card.on("tap", self.open_note)
        title = self.label(
            note.title if note.title.strip() != "" else "Untitled",
            "note-title-" + note.id,
            "text-base font-medium text-slate-900",
        )
        title.fontSize = 15
        title.fontWeight = "500"
        card.addChild(title)
        if note.is_checklist():
            card.addChild(self.checklist_preview(note))
        elif note.body.strip() != "":
            body = self.label(
                note.body,
                "note-preview-" + note.id,
                "mt-1 text-sm text-slate-700",
            )
            body.fontSize = 14
            card.addChild(body)
        return card

    def estimate_note_height(self, note: Note) -> float:
        height = 54.0
        if len(note.title) > 24:
            height += 20
        if note.is_checklist():
            for item in note.items:
                height += 22 + (len(item.text) // 24) * 16
        elif note.body != "":
            height += 28 + (len(note.body) // 32) * 16
        return height

    def empty_state(self) -> StackLayout:
        empty = StackLayout()
        empty.verticalAlignment = "middle"
        titles = {"notes": "No notes yet", "archive": "Archive is empty", "trash": "Trash is empty"}
        messages = {
            "notes": "Create a note or checklist to get started.",
            "archive": "Archived notes appear here.",
            "trash": "Deleted notes appear here.",
        }
        title = "No matching notes" if self.query.strip() != "" else titles[self.view]
        message = "Try a different search." if self.query.strip() != "" else messages[self.view]
        empty.addChild(
            self.label(title, "empty-title", "text-center text-xl font-semibold text-slate-800")
        )
        empty.addChild(
            self.label(
                message,
                "empty-message",
                "mx-8 mt-2 text-center text-base text-slate-500",
            )
        )
        return empty

    def render_notes_content(self):
        if isinstance(self.note_reorder, MasonryReorderController):
            self.note_reorder.dispose()
        self.note_reorder = None
        self.list_content.removeChildren()
        notes = self.visible_notes()
        if len(notes) == 0:
            self.list_content.addChild(self.empty_state())
            return
        views: list[View] = []
        heights: list[float] = []
        groups: list[str] = []
        assigned_columns: list[int] = []
        for note in notes:
            views.append(self.note_card(note))
            heights.append(self.estimate_note_height(note))
            groups.append("pinned" if note.pinned else "notes")
            assigned_column = -1
            if note.grid_column_count > 0:
                assigned_column = note.grid_column
            assigned_columns.append(assigned_column)
        layout = MasonryLayout(
            maximum_column_count=1 if self.layout_mode == "list" else 4,
            group_spacing=17,
            group_separator_color="#cbd5e1",
        )
        layout.id = "note-collection"
        layout.testID = "note-collection"
        layout.className = "bg-white px-1 py-2"
        for note in notes:
            if note.grid_column_count != layout.column_count:
                assigned_columns = []
        layout.set_items(views, heights, groups, assigned_columns)
        self.note_reorder = MasonryReorderController(
            layout,
            self.reorder_notes,
        )
        if len(layout.group_separators) == 1:
            separator = layout.group_separators[0]
            separator.id = "pinned-notes-divider"
            separator.testID = separator.id
        self.list_content.addChild(layout)

    def render_home(self):
        self.root.rows = "auto,*"
        self.root.columns = "*"
        self.root.className = "bg-white"
        toolbar = GridLayout()
        toolbar.columns = "auto,*"
        toolbar.className = "bg-white px-2 py-2"
        menu = self.icon_button(ICON_MENU, "open-navigation", "Open navigation")
        menu.width = 48
        menu.height = 48
        menu.on(Button.tapEvent, self.open_navigation_drawer)
        toolbar.addChild(menu)
        search_surface = GridLayout()
        search_surface.column = 1
        search_surface.columns = "*,auto"
        search_surface.className = "rounded-full bg-slate-100 pl-4 pr-1"
        search_surface.height = 48
        search = TextField()
        search.id = "search-notes"
        search.testID = "search-notes"
        search.text = self.query
        search.hint = "Search notes"
        search.returnKeyType = "search"
        search.className = "h-12 border-0 bg-transparent text-base text-slate-900"
        search.height = 46
        search.accessibilityLabel = "Search notes"
        search.on(TextField.textChangeEvent, self.search_notes)
        search_surface.addChild(search)
        toggle = self.icon_button(
            ICON_LIST if self.layout_mode == "grid" else ICON_GRID,
            "toggle-layout",
            "Show notes as a list" if self.layout_mode == "grid" else "Show notes as a grid",
        )
        toggle.column = 1
        toggle.width = 44
        toggle.height = 44
        toggle.on(Button.tapEvent, self.toggle_layout)
        search_surface.addChild(toggle)
        toolbar.addChild(search_surface)
        self.root.addChild(toolbar)
        self.list_content = GridLayout()
        self.list_content.id = "notes-list"
        self.list_content.testID = "notes-list"
        self.list_content.row = 1
        self.list_content.className = "bg-white"
        self.render_notes_content()
        self.root.addChild(self.list_content)
        if self.view == "notes":
            self.render_creation_controls()

    def render_creation_controls(self):
        controls = StackLayout()
        controls.id = "creation-controls"
        controls.testID = "creation-controls"
        controls.rowSpan = 2
        controls.width = 176
        controls.margin = 16
        controls.horizontalAlignment = "right"
        controls.verticalAlignment = "bottom"
        if self.creation_menu_visible:
            text_note = self.button(
                "Text note",
                "new-text-note",
                "mb-2 rounded-full border border-slate-200 bg-white px-4 text-base font-medium",
            )
            text_note.height = 48
            text_note.on(Button.tapEvent, self.create_text_note)
            controls.addChild(text_note)
            checklist = self.button(
                "Checklist",
                "new-checklist",
                "mb-2 rounded-full border border-slate-200 bg-white px-4 text-base font-medium",
            )
            checklist.height = 48
            checklist.on(Button.tapEvent, self.create_checklist)
            controls.addChild(checklist)
        add = self.icon_button(
            ICON_CLOSE if self.creation_menu_visible else ICON_ADD,
            "new-note-plus",
            "Close create menu" if self.creation_menu_visible else "Create note",
        )
        add.width = 56
        add.height = 56
        add.borderRadius = 18
        add.backgroundColor = "#c2e7ff"
        add.horizontalAlignment = "right"
        add.on(Button.tapEvent, self.toggle_creation_menu)
        controls.addChild(add)
        self.root.addChild(controls)

    def drawer_item(self, view: str, text: str, icon: str) -> GridLayout:
        item = GridLayout()
        item.id = "drawer-" + view
        item.testID = item.id
        item.columns = "56,*"
        item.height = 48
        item.width = 304
        item.marginRight = 12
        item.className = "rounded-r-full"
        item.backgroundColor = "#c2e7ff" if self.view == view else "#ffffff"
        item.on("tap", self.select_view)
        glyph = self.label(icon, "drawer-icon-" + view, "text-center text-slate-700")
        glyph.column = 0
        glyph.fontFamily = MATERIAL_FONT
        glyph.fontSize = 22
        glyph.verticalAlignment = "middle"
        item.addChild(glyph)
        label = self.label(text, "drawer-label-" + view, "text-base text-slate-800")
        label.column = 1
        label.fontWeight = "500" if self.view == view else "400"
        label.verticalAlignment = "middle"
        item.addChild(label)
        item.accessible = True
        item.accessibilityLabel = text
        item.accessibilityRole = "button"
        return item

    def render_navigation_drawer(self):
        overlay = GridLayout()
        overlay.id = "navigation-drawer"
        overlay.testID = overlay.id
        overlay.rowSpan = 2
        scrim = Label()
        scrim.id = "navigation-drawer-scrim"
        scrim.backgroundColor = "#000000"
        scrim.opacity = 0.32
        scrim.on("tap", self.dismiss_navigation_drawer)
        overlay.addChild(scrim)
        drawer = StackLayout()
        drawer.id = "navigation-drawer-content"
        drawer.width = 320
        drawer.horizontalAlignment = "left"
        drawer.verticalAlignment = "stretch"
        drawer.backgroundColor = "#ffffff"
        heading = self.label(
            "Notes",
            "navigation-drawer-title",
            "px-6 pb-4 pt-5 text-xl font-medium text-slate-800",
        )
        heading.height = 72
        drawer.addChild(heading)
        drawer.addChild(self.drawer_item("notes", "Notes", ICON_NOTES))
        drawer.addChild(self.drawer_item("archive", "Archive", ICON_ARCHIVE))
        drawer.addChild(self.drawer_item("trash", "Trash", ICON_DELETE))
        overlay.addChild(drawer)
        self.root.addChild(overlay)

    def render_editor(self, note: Note):
        self.root.rows = "auto,*,auto"
        self.root.columns = "*"
        self.root.className = "bg-white"
        toolbar = GridLayout()
        toolbar.columns = "auto,*,auto,auto"
        toolbar.height = 56
        toolbar.className = "px-2 py-1"
        toolbar.backgroundColor = note.color
        back = self.icon_button(ICON_BACK, "editor-back", "Back")
        back.width = 48
        back.height = 48
        back.on(Button.tapEvent, self.close_editor)
        toolbar.addChild(back)
        pin = self.icon_button(
            ICON_PIN,
            "editor-pin",
            "Unpin note" if note.pinned else "Pin note",
        )
        pin.column = 2
        pin.width = 44
        pin.height = 44
        pin.borderRadius = 22
        pin.backgroundColor = "#c2e7ff" if note.pinned else "transparent"
        pin.on(Button.tapEvent, self.toggle_pin)
        toolbar.addChild(pin)
        archive = self.icon_button(ICON_ARCHIVE, "editor-archive", "Archive note")
        archive.column = 3
        archive.width = 44
        archive.height = 44
        archive.on(Button.tapEvent, self.archive_note)
        toolbar.addChild(archive)
        self.root.addChild(toolbar)
        content = StackLayout()
        content.id = "editor-surface"
        content.testID = content.id
        content.className = "px-4 pb-8 pt-2"
        content.backgroundColor = note.color
        title = TextField()
        title.id = "editor-title"
        title.testID = title.id
        title.text = note.title
        title.hint = "Title"
        title.height = 48
        title.fontSize = 20
        title.fontWeight = "500"
        title.className = "mb-1 h-12 border-0 bg-transparent px-0 text-xl text-slate-900"
        title.on(TextField.textChangeEvent, self.change_title)
        content.addChild(title)
        if note.is_checklist():
            for item in note.items:
                content.addChild(self.checklist_row(item))
            add_item = self.button(
                "+  List item",
                "add-checklist-item",
                "h-12 bg-transparent text-left text-base text-slate-600",
            )
            add_item.on(Button.tapEvent, self.add_checklist_item)
            content.addChild(add_item)
        else:
            body = TextView()
            body.id = "editor-body"
            body.testID = body.id
            body.text = note.body
            body.hint = "Note"
            body.fontSize = 16
            body.className = "min-h-64 border-0 bg-transparent px-0 text-base text-slate-900"
            body.on(TextView.textChangeEvent, self.change_body)
            content.addChild(body)
        scroll = ScrollView()
        scroll.id = "editor-scroll"
        scroll.row = 1
        scroll.backgroundColor = note.color
        scroll.content = content
        self.root.addChild(scroll)
        footer = StackLayout()
        footer.row = 2
        footer.backgroundColor = note.color
        bar = GridLayout()
        bar.columns = "auto,*,auto"
        bar.height = 48
        palette = self.icon_button(ICON_PALETTE, "toggle-colors", "Show note colors")
        palette.width = 48
        palette.height = 48
        palette.on(Button.tapEvent, self.toggle_palette)
        bar.addChild(palette)
        status = self.label(
            "On this device", "storage-status", "text-center text-xs text-slate-500"
        )
        status.column = 1
        status.verticalAlignment = "middle"
        bar.addChild(status)
        more = self.icon_button(ICON_MORE, "editor-more", "More note actions")
        more.column = 2
        more.width = 48
        more.height = 48
        more.on(Button.tapEvent, self.open_note_actions)
        bar.addChild(more)
        footer.addChild(bar)
        colors = self.color_palette(note)
        colors.visibility = "visible" if self.palette_visible else "collapse"
        footer.addChild(colors)
        self.root.addChild(footer)

    def action_button(
        self,
        text: str,
        test_id: str,
        callback: callable,
        destructive: bool = False,
    ) -> Button:
        class_name = "h-12 bg-transparent text-left text-base font-medium text-slate-800"
        if destructive:
            class_name = (
                "h-12 bg-transparent text-left text-base font-semibold text-red-700"
            )
        action = self.button(text, test_id, class_name)
        action.on(Button.tapEvent, callback)
        return action

    def render_note_actions(self, note: Note):
        overlay = GridLayout()
        overlay.id = "note-actions"
        overlay.testID = overlay.id
        overlay.rowSpan = 3
        scrim = Label()
        scrim.id = "note-actions-scrim"
        scrim.testID = scrim.id
        scrim.backgroundColor = "#000000"
        scrim.opacity = 0.32
        scrim.on("tap", self.dismiss_note_actions)
        overlay.addChild(scrim)
        sheet = StackLayout()
        sheet.id = "note-actions-content"
        sheet.testID = sheet.id
        sheet.margin = "0 12 12 12"
        sheet.padding = "12 16 20 16"
        sheet.horizontalAlignment = "stretch"
        sheet.verticalAlignment = "bottom"
        sheet.backgroundColor = "#ffffff"
        sheet.borderColor = "#dadce0"
        sheet.borderWidth = 1
        sheet.borderRadius = 20
        heading = self.label(
            note.title if note.title.strip() != "" else "Untitled",
            "note-actions-title",
            "mb-2 px-3 text-lg font-medium text-slate-900",
        )
        heading.height = 48
        heading.verticalAlignment = "middle"
        sheet.addChild(heading)
        sheet.addChild(
            self.action_button("Make a copy", "copy-note", self.copy_note)
        )
        sheet.addChild(
            self.action_button("Delete", "delete-note", self.trash_note, True)
        )
        overlay.addChild(sheet)
        self.root.addChild(overlay)

    def checklist_row(self, item: ChecklistItem) -> GridLayout:
        row = GridLayout()
        row.columns = "44,*"
        row.height = 48
        toggle = self.icon_button(
            ICON_CHECKED if item.checked else ICON_CHECKBOX,
            "toggle-item-" + item.id,
            item.text,
            22,
        )
        toggle.width = 44
        toggle.height = 48
        toggle.on(Button.tapEvent, self.toggle_checklist_item)
        row.addChild(toggle)
        field = TextField()
        field.id = item.id
        field.testID = "item-input-" + item.id
        field.column = 1
        field.text = item.text
        field.className = (
            "h-12 border-0 bg-transparent px-1 text-base text-slate-500 line-through"
            if item.checked
            else "h-12 border-0 bg-transparent px-1 text-base text-slate-900"
        )
        field.on(TextField.textChangeEvent, self.change_checklist_item)
        row.addChild(field)
        return row

    def color_palette(self, note: Note) -> GridLayout:
        palette = GridLayout()
        palette.id = "color-palette"
        palette.testID = palette.id
        palette.columns = "*,*,*,*,*,*"
        palette.className = "px-3 pb-2"
        colors = ["#ffffff", "#fff475", "#ccff90", "#cbf0f8", "#f28b82", "#d7aefb"]
        names = ["white", "lemon", "mint", "sky", "coral", "lilac"]
        for index in range(len(colors)):
            button = self.button(
                "✓" if note.color == colors[index] else "",
                "color-" + names[index],
                "m-1 h-9 rounded-full border border-slate-400 text-slate-800",
            )
            button.column = index
            button.height = 36
            button.backgroundColor = colors[index]
            button.accessibilityLabel = names[index] + " note color"
            button.on(Button.tapEvent, self.choose_color)
            palette.addChild(button)
        return palette

    def render(self):
        if isinstance(self.note_reorder, MasonryReorderController):
            self.note_reorder.dispose()
        self.note_reorder = None
        self.root.removeChildren()
        note = self.current_note()
        if note is not None:
            self.render_editor(note)
            return
        self.render_home()
        if self.navigation_drawer_visible:
            self.render_navigation_drawer()

    def open_note(self, event: EventData):
        if (
            isinstance(self.note_reorder, MasonryReorderController)
            and self.note_reorder.consume_suppressed_tap(event.object.id)
        ):
            return
        note = self.note(event.object.id)
        if note is not None:
            self.editing_id = note.id
            self.palette_visible = False
            self.action_sheet_visible = False
            self.render()

    def reorder_notes(self, result: MasonryReorderResult):
        notes_by_id: dict[str, Note] = {}
        for note in self.notes:
            notes_by_id[note.id] = note
        reordered: list[Note] = []
        for item_id in result.item_ids:
            if item_id in notes_by_id:
                reordered.append(notes_by_id[item_id])
        visible_ids = set(result.item_ids)
        visible_index = 0
        for index in range(len(self.notes)):
            if self.notes[index].id in visible_ids:
                self.notes[index] = reordered[visible_index]
                visible_index += 1
        if self.layout_mode == "grid":
            for index in range(len(result.item_ids)):
                note = notes_by_id[result.item_ids[index]]
                note.grid_column = result.columns[index]
                note.grid_column_count = result.column_count

    def close_editor(self, _event: EventData | None = None):
        self.editing_id = ""
        self.palette_visible = False
        self.action_sheet_visible = False
        self.render()

    def search_notes(self, event: EventData):
        if isinstance(event.object, TextField):
            self.query = event.object.text
            self.render_notes_content()

    def toggle_layout(self, _event: EventData):
        self.layout_mode = "list" if self.layout_mode == "grid" else "grid"
        self.render()

    def toggle_creation_menu(self, _event: EventData):
        self.creation_menu_visible = not self.creation_menu_visible
        self.render()

    def next_id(self, prefix: str) -> str:
        value = prefix + "-" + str(self.sequence)
        self.sequence += 1
        return value

    def create_text_note(self, _event: EventData):
        note = Note(self.next_id("note"), "", "")
        self.notes.insert(0, note)
        self.creation_menu_visible = False
        self.editing_id = note.id
        self.render()

    def create_checklist(self, _event: EventData):
        item = ChecklistItem(self.next_id("item"), "")
        note = Note(self.next_id("note"), "", items=[item])
        self.notes.insert(0, note)
        self.creation_menu_visible = False
        self.editing_id = note.id
        self.render()

    def change_title(self, event: EventData):
        note = self.current_note()
        if note is not None and isinstance(event.object, TextField):
            note.title = event.object.text

    def change_body(self, event: EventData):
        note = self.current_note()
        if note is not None and isinstance(event.object, TextView):
            note.body = event.object.text

    def checklist_item(self, item_id: str) -> ChecklistItem | None:
        note = self.current_note()
        if note is not None:
            for item in note.items:
                if item.id == item_id:
                    return item
        return None

    def toggle_checklist_item(self, event: EventData):
        item_id = event.object.id.removeprefix("toggle-item-")
        item = self.checklist_item(item_id)
        if item is not None:
            item.checked = not item.checked
            self.render()

    def change_checklist_item(self, event: EventData):
        item = self.checklist_item(event.object.id)
        if item is not None and isinstance(event.object, TextField):
            item.text = event.object.text

    def add_checklist_item(self, _event: EventData):
        note = self.current_note()
        if note is not None:
            note.items.append(ChecklistItem(self.next_id("item"), ""))
            self.render()

    def toggle_pin(self, _event: EventData):
        note = self.current_note()
        if note is not None:
            note.pinned = not note.pinned
            self.render()

    def archive_note(self, _event: EventData):
        note = self.current_note()
        if note is not None:
            note.archived = not note.archived
            note.trashed = False
            self.close_editor()

    def trash_note(self, _event: EventData):
        note = self.current_note()
        if note is not None:
            note.trashed = True
            note.archived = False
            self.close_editor()

    def open_note_actions(self, _event: EventData):
        note = self.current_note()
        if note is not None:
            self.action_sheet_visible = True
            self.render_note_actions(note)

    def dismiss_note_actions(self, _event: EventData | None = None):
        self.action_sheet_visible = False
        overlay = self.root.getViewById("note-actions")
        if overlay is not None and self.root.getChildIndex(overlay) >= 0:
            self.root.removeChild(overlay)

    def copy_note(self, _event: EventData):
        note = self.current_note()
        if note is None:
            return
        items: list[ChecklistItem] = []
        for item in note.items:
            items.append(
                ChecklistItem(self.next_id("item"), item.text, item.checked)
            )
        copy = Note(
            self.next_id("note"),
            note.title + " (copy)",
            note.body,
            note.color,
            items=items,
        )
        self.notes.insert(0, copy)
        self.editing_id = copy.id
        self.action_sheet_visible = False
        self.render()

    def toggle_palette(self, _event: EventData):
        self.palette_visible = not self.palette_visible
        palette = self.root.getViewById("color-palette")
        if palette is not None:
            palette.visibility = "visible" if self.palette_visible else "collapse"

    def choose_color(self, event: EventData):
        note = self.current_note()
        if note is None:
            return
        colors = {
            "color-white": "#ffffff",
            "color-lemon": "#fff475",
            "color-mint": "#ccff90",
            "color-sky": "#cbf0f8",
            "color-coral": "#f28b82",
            "color-lilac": "#d7aefb",
        }
        note.color = colors[event.object.id]
        self.render()

    def open_navigation_drawer(self, _event: EventData):
        self.navigation_drawer_visible = True
        self.render_navigation_drawer()

    def dismiss_navigation_drawer(self, _event: EventData | None = None):
        self.navigation_drawer_visible = False
        drawer = self.root.getViewById("navigation-drawer")
        if drawer is not None and self.root.getChildIndex(drawer) >= 0:
            self.root.removeChild(drawer)

    def select_view(self, event: EventData):
        self.view = event.object.id.removeprefix("drawer-")
        self.query = ""
        self.navigation_drawer_visible = False
        self.render()

    def android_back_pressed(self, event: AndroidActivityBackPressedEventData):
        if self.action_sheet_visible:
            event.cancel = True
            self.dismiss_note_actions()
        elif self.navigation_drawer_visible:
            event.cancel = True
            self.dismiss_navigation_drawer()
        elif self.editing_id != "":
            event.cancel = True
            self.close_editor()
        elif self.creation_menu_visible:
            event.cancel = True
            self.creation_menu_visible = False
            self.render()

    def page(self) -> Page:
        return self.page_view


@js
def create_page() -> Page:
    return NotesApp().page()


@js
def main():
    Application.run(create_page)


def run() -> None:
    project = NativeScriptProject(
        main,
        name="Notes",
        app_id="org.pyjs.notes",
        app_assets=APP_ASSETS,
    )
    device = project.run_android()
    print(f"PyJS Notes is running on {device.identifier}.")


if __name__ == "__main__":
    run()
