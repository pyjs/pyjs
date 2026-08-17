from pyjs import js

from . import EventData, NativeScriptModule, View

COLLECTION_VIEW_MODULE = NativeScriptModule(
    "@nativescript-community/ui-collectionview",
    "6.0.25",
    ("CollectionView", "CollectionViewBase"),
)


@js.inline(
    "new androidx.recyclerview.widget.StaggeredGridLayoutManager("
    "{span_count}, "
    "androidx.recyclerview.widget.StaggeredGridLayoutManager.VERTICAL)"
)
def android_staggered_grid_layout(span_count: int) -> object: ...


@js.native
class CollectionViewBase(View):
    @staticmethod
    def registerLayoutStyle(style: str, generator: dict[str, callable]): ...


@js.inline(
    "CollectionViewBase.registerLayoutStyle("
    "{style}, {{ createLayout: {create_layout} }})"
)
def register_collection_layout(style: str, create_layout: callable) -> None: ...


@js.native
class CollectionViewItemEventData(EventData):
    def __init__(self):
        super().__init__()
        self.index = -1
        self.view: View | None = None
        self.item = object()
        self.bindingContext = object()


@js.native
class CollectionViewReorderData:
    def __init__(self):
        self.targetIndex = -1


@js.native
class CollectionViewReorderEventData(CollectionViewItemEventData):
    def __init__(self):
        super().__init__()
        self.data = CollectionViewReorderData()
        self.returnValue = True


@js.native
class CollectionView(View):
    itemLoadingEvent = "itemLoading"
    itemReorderedEvent = "itemReordered"
    itemReorderCheckEvent = "itemReorderCheck"
    itemReorderStartingEvent = "itemReorderStarting"

    def __init__(self):
        super().__init__()
        self.items = object()
        self.testViews: list[View] = []
        self.rowHeight: int | str = "auto"
        self.colWidth: int | str = "auto"
        self.orientation = "vertical"
        self.layoutStyle = "grid"
        self.isScrollEnabled = True
        self.scrollBarIndicatorVisible = True
        self.reorderEnabled = False
        self.reorderLongPressEnabled = True

    def getViewById(self, view_id: str) -> View | None:
        if self.id == view_id:
            return self
        for view in self.testViews:
            match = view.getViewById(view_id)
            if match is not None:
                return match
        return None

    def refresh(self): ...

    def refreshVisibleItems(self): ...

    def scrollToIndex(self, index: int, animated: bool = False): ...

    def startDragging(self, index: int, pointer: object | None = None): ...


__all__ = [
    "COLLECTION_VIEW_MODULE",
    "CollectionView",
    "CollectionViewBase",
    "CollectionViewItemEventData",
    "CollectionViewReorderData",
    "CollectionViewReorderEventData",
    "android_staggered_grid_layout",
    "register_collection_layout",
]
