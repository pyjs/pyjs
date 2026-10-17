from typing import cast

from pyjs import js
from pyjs.web.dom import Element, window
from pyjs.web.domx import ProxyElement, div, tw
from pyjs.web.events import Event, KeyboardEvent, PointerEvent
from pyjs.web.ui import Widget


@js
class ResizablePanel(ProxyElement):
    def __init__(self, *children, initial_size: int = 50):
        self.element = div(
            tw("min-h-0 min-w-0 overflow-auto"),
            {
                "data-size": str(initial_size),
                "data-slot": "resizable-panel",
                "style": "flex-basis: " + str(initial_size) + "%",
            },
            *children,
        )

    def current_size(self) -> float:
        value = self.getAttribute("data-size")
        if value is None:
            return 0.0
        return float(value)

    def set_size(self, size: float):
        self.setAttribute("data-size", str(size))
        self.setAttribute("style", "flex-basis: " + str(size) + "%")


@js
class ResizableHandle(ProxyElement):
    def __init__(self, with_handle: bool = False):
        self.element = div(
            tw(
                "relative flex w-1 shrink-0 cursor-col-resize items-center justify-center "
                "bg-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-slate-400 "
                "data-[direction=vertical]:h-1 data-[direction=vertical]:w-full "
                "data-[direction=vertical]:cursor-row-resize"
            ),
            {
                "aria-label": "Resize panels",
                "aria-valuemax": "90",
                "aria-valuemin": "10",
                "data-slot": "resizable-handle",
                "role": "separator",
                "tabindex": "0",
            },
            "⋮" if with_handle else "",
        )


@js
class ResizableMoveListener:
    def __init__(self, group: ResizablePanelGroup):
        self.group = group

    def handleEvent(self, event: PointerEvent):
        self.group.pointer_moved(event)


@js
class ResizableUpListener:
    def __init__(self, group: ResizablePanelGroup):
        self.group = group

    def handleEvent(self, event: PointerEvent):
        self.group.pointer_released(event)


@js
class ResizablePanelGroup(Widget):
    def __init__(
        self,
        *children: ProxyElement,
        direction: str = "horizontal",
        framed: bool = True,
        min_size: int = 10,
    ):
        super().__init__()
        self.drag_index = -1
        self.drag_start = 0
        self.before_start = 0.0
        self.after_start = 0.0
        self.move_listener = ResizableMoveListener(self)
        self.up_listener = ResizableUpListener(self)
        for child in children:
            if isinstance(child, ResizableHandle):
                child.setAttribute("data-direction", direction)
        if framed:
            classes = tw(
                "flex min-h-48 w-full overflow-hidden rounded-lg border border-slate-200 "
                "data-[direction=vertical]:flex-col"
            )
        else:
            classes = tw(
                "flex min-h-0 w-full overflow-hidden data-[direction=vertical]:flex-col"
            )
        self.add(
            classes,
            {
                "data-direction": direction,
                "data-min-size": str(min_size),
                "data-slot": "resizable-panel-group",
            },
            *children,
        )
        self.addEventListener("keydown", self.keydown)
        self.addEventListener("pointerdown", self.pointer_pressed)
        self.update_handle_values()

    def initialize(self):
        self.drag_index = -1
        self.drag_start = 0
        self.before_start = 0.0
        self.after_start = 0.0
        self.move_listener = ResizableMoveListener(self)
        self.up_listener = ResizableUpListener(self)

    def min_panel_size(self) -> float:
        value = self.getAttribute("data-min-size")
        if value is None:
            return 10.0
        size = float(value)
        if size < 1:
            return 1.0
        return size

    def is_vertical(self) -> bool:
        return self.getAttribute("data-direction") == "vertical"

    def panel_elements(self) -> list[Element]:
        panels: list[Element] = []
        for child in self.children:
            if child.getAttribute("data-slot") == "resizable-panel":
                panels.append(child)
        return panels

    def handle_elements(self) -> list[Element]:
        handles: list[Element] = []
        for child in self.children:
            if child.getAttribute("data-slot") == "resizable-handle":
                handles.append(child)
        return handles

    def current_size(self, panel: Element) -> float:
        value = panel.getAttribute("data-size")
        return 0.0 if value is None else float(value)

    def set_size(self, panel: Element, size: float):
        panel.setAttribute("data-size", str(size))
        panel.setAttribute("style", "flex-basis: " + str(size) + "%")

    def resize_pair(self, index: int, before_size: float, after_size: float):
        floor = self.min_panel_size()
        pair_total = before_size + after_size
        ceiling = pair_total - floor
        if before_size < floor:
            before_size = floor
            after_size = ceiling
        elif after_size < floor:
            before_size = ceiling
            after_size = floor
        panels = self.panel_elements()
        self.set_size(panels[index], before_size)
        self.set_size(panels[index + 1], after_size)
        self.update_handle_values()

    def update_handle_values(self):
        panels = self.panel_elements()
        handles = self.handle_elements()
        for index in range(len(handles)):
            handles[index].setAttribute(
                "aria-valuenow",
                str(round(self.current_size(panels[index]))),
            )

    def handle_index(self, target: Element) -> int:
        handles = self.handle_elements()
        for index in range(len(handles)):
            if handles[index] is target:
                return index
        return -1

    def keydown(self, event: KeyboardEvent):
        target = cast(Element, event.target)
        handle = target.closest("[data-slot=resizable-handle]")
        if handle is None:
            return
        delta = 0
        if event.key == "ArrowLeft" or event.key == "ArrowUp":
            delta = -2
        elif event.key == "ArrowRight" or event.key == "ArrowDown":
            delta = 2
        if delta == 0:
            return
        index = self.handle_index(handle)
        if index < 0:
            return
        event.preventDefault()
        panels = self.panel_elements()
        self.resize_pair(
            index,
            self.current_size(panels[index]) + delta,
            self.current_size(panels[index + 1]) - delta,
        )

    def pointer_pressed(self, event: PointerEvent):
        target = cast(Element, event.target)
        handle = target.closest("[data-slot=resizable-handle]")
        if handle is None:
            return
        index = self.handle_index(handle)
        if index < 0:
            return
        event.preventDefault()
        panels = self.panel_elements()
        self.drag_index = index
        self.drag_start = event.clientY if self.is_vertical() else event.clientX
        self.before_start = self.current_size(panels[index])
        self.after_start = self.current_size(panels[index + 1])
        window.addEventListener("pointermove", self.move_listener)
        window.addEventListener("pointerup", self.up_listener)

    def pointer_moved(self, event: PointerEvent):
        if self.drag_index < 0:
            return
        bounds = self.getBoundingClientRect()
        current = event.clientY if self.is_vertical() else event.clientX
        total = bounds.height if self.is_vertical() else bounds.width
        if total <= 0:
            return
        delta = (current - self.drag_start) / total * 100
        self.resize_pair(
            self.drag_index,
            self.before_start + delta,
            self.after_start - delta,
        )

    def pointer_released(self, event: Event):
        self.stop_drag()

    def stop_drag(self):
        window.removeEventListener("pointermove", self.move_listener)
        window.removeEventListener("pointerup", self.up_listener)
        self.drag_index = -1

    def disconnected(self):
        if self.drag_index >= 0:
            self.stop_drag()
