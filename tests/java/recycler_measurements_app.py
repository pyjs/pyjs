from pyjs.android import (
    Activity,
    Bundle,
    LinearLayout,
    LinearLayoutParams,
    TextView,
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
from tests.staggered_calibration_cases import heights


class Card(RecyclerViewViewHolder):
    def __init__(self, view: View) -> None:
        super().__init__(view)


class Cards(RecyclerViewAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.set_has_stable_ids(True)

    def get_item_count(self) -> i32:
        return 8

    def get_item_id(self, position: i32) -> int:
        return 100 + position

    def on_create_view_holder(self, parent: ViewGroup, kind: i32) -> RecyclerViewViewHolder:
        return Card(TextView(parent.getContext()))

    def on_bind_view_holder(self, holder: RecyclerViewViewHolder, position: i32) -> None:
        full = position == 0 or position == 4
        # StaggeredGrid subtracts margins from an exact height measure spec.
        height = heights()[position] if full else heights()[position] + 14
        params = StaggeredGridLayoutParams(-1, height)
        params.set_full_span(full)
        if not full:
            params.setMargins(3, 5, 7, 9)
        holder.item_view.setLayoutParams(params)


class CalibrationActivity(Activity):
    def columns(self) -> i32:
        return 2

    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        recycler = RecyclerView(self)
        recycler.setId(100)
        recycler.set_layout_manager(StaggeredGridLayoutManager(self.columns(), 1))
        recycler.set_adapter(Cards())
        recycler.setLayoutParams(LinearLayoutParams(601, 400, 0.0))
        root = LinearLayout(self)
        root.addView(recycler)
        self.setContentView(root)


class ThreeColumnActivity(CalibrationActivity):
    def columns(self) -> i32:
        return 3


class FourColumnActivity(CalibrationActivity):
    def columns(self) -> i32:
        return 4
