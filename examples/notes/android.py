from typing import cast

from pyjs.android import (
    Activity,
    Application,
    Bundle,
    GradientDrawable,
    LayoutParams,
    LinearLayout,
    LinearLayoutParams,
    OnClickListener,
    TextView,
    View,
    ViewGroup,
    parse_color,
)
from pyjs.android.recyclerview import (
    ItemTouchCallback,
    ItemTouchHelper,
    RecyclerView,
    RecyclerViewAdapter,
    RecyclerViewLayoutParams,
    RecyclerViewViewHolder,
    StaggeredGridLayoutManager,
    make_movement_flags,
)
from pyjs.java import f32, i32

from .android_saves import BackgroundSaveDriver
from .android_storage import OrderFile, OrderObserver, OrderSession


class NoteHolder(RecyclerViewViewHolder):
    def __init__(self, view: TextView) -> None:
        super().__init__(view)

    def bind(self, text: str, color: str) -> None:
        label = cast(TextView, self.item_view)
        label.setText(text)
        label.setContentDescription(text)

        background = GradientDrawable()
        background.setColor(parse_color(color))
        background.setCornerRadius(24.0)
        background.setStroke(2, parse_color("#dadce0"))
        label.setBackground(background)


class NotesAdapter(RecyclerViewAdapter):
    def __init__(
        self,
        notes: list[str],
        colors: list[str],
        note_ids: list[int],
        session: OrderSession | None = None,
        status: TextView | None = None,
    ) -> None:
        super().__init__()
        self.notes = notes
        self.colors = colors
        self.note_ids = note_ids
        self.session = session
        self.status = status
        self.set_has_stable_ids(True)

    def on_create_view_holder(
        self,
        parent: ViewGroup,
        view_type: i32,
    ) -> RecyclerViewViewHolder:
        note = TextView(parent.getContext())
        note.setTextSize(15.0)
        note.setTextColor(parse_color("#202124"))
        note.setPadding(32, 28, 32, 28)

        params = RecyclerViewLayoutParams(
            LayoutParams.MATCH_PARENT,
            LayoutParams.WRAP_CONTENT,
        )
        params.setMargins(12, 12, 12, 12)
        note.setLayoutParams(params)
        return NoteHolder(note)

    def on_bind_view_holder(
        self,
        holder: RecyclerViewViewHolder,
        position: i32,
    ) -> None:
        cast(NoteHolder, holder).bind(
            self.notes[position],
            self.colors[position],
        )

    def get_item_count(self) -> i32:
        return len(self.notes)

    def get_item_id(self, position: i32) -> int:
        return self.note_ids[position]

    def move(self, source: i32, target: i32, changed: bool = True) -> None:
        note = self.notes[source]
        color = self.colors[source]
        note_id = self.note_ids[source]
        if source < target:
            for index in range(source, target):
                self.notes[index] = self.notes[index + 1]
                self.colors[index] = self.colors[index + 1]
                self.note_ids[index] = self.note_ids[index + 1]
        elif source > target:
            for index in range(source, target, -1):
                self.notes[index] = self.notes[index - 1]
                self.colors[index] = self.colors[index - 1]
                self.note_ids[index] = self.note_ids[index - 1]
        self.notes[target] = note
        self.colors[target] = color
        self.note_ids[target] = note_id
        self.notify_item_moved(source, target)
        if self.session is not None and source != target and changed:
            self.session.changed(self.note_ids)

    def restore_order(self) -> None:
        if self.session is not None:
            order = self.session.restore(self.note_ids)
            for target in range(len(order)):
                for source in range(target, len(self.note_ids)):
                    if self.note_ids[source] == order[target]:
                        self.move(source, target, False)
                        break
        self.show_storage_status()

    def save_order(self) -> None:
        if self.session is not None:
            self.session.save(self.note_ids)
        self.show_storage_status()

    def show_storage_status(self) -> None:
        if self.session is not None and self.status is not None:
            self.status.setText(self.session.message)
            self.status.setVisibility(0 if self.session.message != "" else 8)


class RetrySave(OnClickListener):
    def __init__(self, adapter: NotesAdapter) -> None:
        self.adapter = adapter

    def onClick(self, view: View) -> None:
        self.adapter.save_order()


class StorageStatus(OrderObserver):
    def __init__(self, adapter: NotesAdapter) -> None:
        self.adapter = adapter

    def storage_changed(self) -> None:
        self.adapter.show_storage_status()


class NotesTouch(ItemTouchCallback):
    def __init__(self, adapter: NotesAdapter) -> None:
        super().__init__()
        self.adapter = adapter

    def get_movement_flags(
        self,
        recycler_view: RecyclerView,
        view_holder: RecyclerViewViewHolder,
    ) -> i32:
        drag = (
            ItemTouchHelper.UP
            | ItemTouchHelper.DOWN
            | ItemTouchHelper.START
            | ItemTouchHelper.END
        )
        return make_movement_flags(drag, 0)

    def is_long_press_drag_enabled(self) -> bool:
        return True

    def is_item_view_swipe_enabled(self) -> bool:
        return False

    def get_move_threshold(self, view_holder: RecyclerViewViewHolder) -> f32:
        return 0.35

    def on_move(
        self,
        recycler_view: RecyclerView,
        view_holder: RecyclerViewViewHolder,
        target: RecyclerViewViewHolder,
    ) -> bool:
        source = view_holder.get_binding_adapter_position()
        destination = target.get_binding_adapter_position()
        if source < 0 or destination < 0 or source == destination:
            return False
        self.adapter.move(source, destination)
        return True

    def on_swiped(
        self,
        view_holder: RecyclerViewViewHolder,
        direction: i32,
    ) -> None:
        pass

    def clear_view(self, recycler_view: RecyclerView,
                   view_holder: RecyclerViewViewHolder) -> None:
        super().clear_view(recycler_view, view_holder)
        self.adapter.save_order()


class NotesApplication(Application):
    session: OrderSession

    def onCreate(self) -> None:
        super().onCreate()
        self.session = OrderSession(
            OrderFile(self.getFilesDir().getPath() + "/notes-order.txt"),
            BackgroundSaveDriver(),
        )


class NotesActivity(Activity):
    storage_observer: StorageStatus

    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)
        self.setTitle("Notes")

        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        root.setFitsSystemWindows(True)
        root.setBackgroundColor(parse_color("#ffffff"))

        search = TextView(self)
        search.setText("☰     Search your notes                         ▦")
        search.setTextSize(16.0)
        search.setTextColor(parse_color("#5f6368"))
        search.setPadding(40, 28, 40, 28)
        search.setElevation(4.0)
        root.addView(search)

        notes = [
            (
                "Launch checklist\n\n✓ Review the final build\n"
                "☐ Capture store screenshots\n☐ Publish the release notes"
            ),
            "Weekend ideas\n\nWalk the river trail\nTry the new bakery\nCall Maya",
            (
                "Groceries\n\n☐ Coffee beans\n☐ Lemons\n"
                "☐ Sourdough bread\n☐ Fresh basil"
            ),
            (
                "Design notes\n\nKeep the hierarchy quiet. Let spacing, color, "
                "and typography do the work before adding another border."
            ),
            (
                "Reading list\n\nDesign Systems\nThe Shape of Design\n"
                "The Design of Everyday Things"
            ),
            (
                "Pasta night\n\nTomatoes, garlic, olive oil, chili, basil, and "
                "plenty of parmesan."
            ),
            (
                "A useful reminder\n\nMake it work, make it clear, then make it "
                "delightful."
            ),
        ]
        colors = [
            "#fff475",
            "#cbf0f8",
            "#ccff90",
            "#ffffff",
            "#d7aefb",
            "#f28b82",
            "#e8eaed",
        ]
        note_ids = [1001, 1002, 1003, 1004, 1005, 1006, 1007]
        recycler = RecyclerView(self)
        recycler.setId(100)
        recycler.set_layout_manager(
            StaggeredGridLayoutManager(
                2,
                StaggeredGridLayoutManager.VERTICAL,
            )
        )
        recycler.set_has_fixed_size(False)
        status = TextView(self)
        status.setId(101)
        status.setTextSize(14.0)
        status.setPadding(40, 16, 40, 16)
        session = cast(NotesApplication, self.getApplicationContext()).session
        adapter = NotesAdapter(notes, colors, note_ids, session, status)
        adapter.restore_order()
        self.storage_observer = StorageStatus(adapter)
        session.attach(self.storage_observer)
        status.setOnClickListener(RetrySave(adapter))
        root.addView(status)
        recycler.set_adapter(adapter)
        ItemTouchHelper(NotesTouch(adapter)).attach_to_recycler_view(recycler)
        recycler.setLayoutParams(
            LinearLayoutParams(LayoutParams.MATCH_PARENT, 0, 1.0)
        )
        root.addView(recycler)
        self.setContentView(root)

    def onDestroy(self) -> None:
        session = self.storage_observer.adapter.session
        if session is not None:
            session.detach(self.storage_observer)
        super().onDestroy()


def main() -> int:
    activity = NotesActivity()
    activity.onCreate(Bundle())
    return 0
