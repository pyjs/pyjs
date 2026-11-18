from typing import cast

from pyjs.android import (
    Activity,
    Bundle,
    LayoutParams,
    LinearLayout,
    OnClickListener,
    TextView,
    TruncateAt,
    View,
    ViewGroup,
)
from pyjs.android.recyclerview import (
    RecyclerView,
    RecyclerViewAdapter,
    RecyclerViewViewHolder,
    StaggeredGridLayoutManager,
    StaggeredGridLayoutParams,
)
from pyjs.java import i32


class Card(RecyclerViewViewHolder):
    def __init__(self, view: View):
        super().__init__(view)
        self.attached = False


class Cards(RecyclerViewAdapter):
    def __init__(self):
        super().__init__()
        self.attached = 0
        self.detached = 0
        self.recycled = 0
        self.bound = 0

    def get_item_count(self) -> i32:
        return 80

    def on_create_view_holder(self, parent: ViewGroup, view_type: i32) -> RecyclerViewViewHolder:
        label = TextView(parent.getContext())
        label.setLayoutParams(StaggeredGridLayoutParams(220, 100))
        return Card(label)

    def on_bind_view_holder(self, holder: RecyclerViewViewHolder, position: i32) -> None:
        cast(TextView, holder.item_view).setText("Row " + str(position))
        self.bound += 1

    def on_view_attached_to_window(self, holder: RecyclerViewViewHolder) -> None:
        super().on_view_attached_to_window(holder)
        card = cast(Card, holder)
        assert not card.attached
        card.attached = True
        self.attached += 1

    def on_view_detached_from_window(self, holder: RecyclerViewViewHolder) -> None:
        super().on_view_detached_from_window(holder)
        card = cast(Card, holder)
        assert card.attached
        card.attached = False
        self.detached += 1

    def on_view_recycled(self, holder: RecyclerViewViewHolder) -> None:
        super().on_view_recycled(holder)
        assert not cast(Card, holder).attached
        self.recycled += 1


class CardsAction(OnClickListener):
    def __init__(self, activity: CardsActivity, action: str):
        self.activity = activity
        self.action = action

    def onClick(self, view: View) -> None:
        if self.action == "far":
            self.activity.recycler.scroll_to_position(40)
        elif self.action == "start":
            self.activity.recycler.scroll_to_position(0)
        else:
            self.activity.recycler.set_adapter(Cards())


class CardsActivity(Activity):
    cards: Cards
    recycler: RecyclerView

    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        self.cards = Cards()
        self.recycler = RecyclerView(self)
        self.recycler.setId(100)
        self.recycler.set_layout_manager(StaggeredGridLayoutManager(1, 1))
        self.recycler.set_adapter(self.cards)
        self.recycler.setLayoutParams(LayoutParams(220, 220))
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        root.addView(self.recycler)
        for action in ["far", "start", "replace"]:
            button = TextView(self)
            button.setText(action)
            button.setContentDescription("Cards " + action)
            # A child that intercepts the tap must fail the parent's scroll check.
            button.setOnClickListener(CardsAction(self, "replace"))
            button.setClickable(False)
            control = LinearLayout(self)
            control.setOnClickListener(CardsAction(self, action))
            control.addView(button)
            root.addView(control)
        self.setContentView(root)


class TextPreviewActivity(Activity):
    original: str

    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        self.original = "A long paragraph with many words and an emoji 😀. " * 12
        for index in range(2):
            label = TextView(self)
            label.setId(i32(200 + index))
            label.setTextSize(16.0)
            label.setMaxLines(2)
            label.setEllipsize(TruncateAt.END)
            if index == 1:
                label.setEllipsize(None)
            label.setText(self.original)
            label.setLayoutParams(LayoutParams(220, LayoutParams.WRAP_CONTENT))
            root.addView(label)
        self.setContentView(root)
