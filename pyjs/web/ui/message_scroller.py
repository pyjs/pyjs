from pyjs import js
from pyjs.web.dom import Element, ResizeObserver
from pyjs.web.domx import ProxyElement, button, div, ref, tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement
from pyjs.web.timers import clearTimeout, setTimeout
from pyjs.web.ui import Widget
from pyjs.web.ui.effects import EFFECTS_CSS, sync_scroll_fade
from pyjs.web.ui.scroll_area import SCROLLBAR_CSS


@js
def MessageScrollerViewport(*children, label: str = "Messages"):
    return div(
        tw(
            "size-full min-h-0 min-w-0 overflow-y-auto overscroll-contain "
            "[scrollbar-gutter:stable]"
        ),
        {
            "aria-label": label,
            "data-scroll-fade": "y",
            "data-slot": "message-scroller-viewport",
            "role": "region",
            "tabindex": "0",
        },
        *children,
    )


@js
def MessageScrollerContent(*children):
    return div(
        tw("flex h-max min-h-full flex-col gap-6 p-4"),
        {
            "aria-relevant": "additions",
            "data-slot": "message-scroller-content",
            "role": "log",
        },
        *children,
    )


@js
def MessageScrollerItem(
    *children,
    scroll_anchor: bool = False,
    message_id: str = "",
):
    attributes = {
        "data-scroll-anchor": "true" if scroll_anchor else "false",
        "data-slot": "message-scroller-item",
    }
    if message_id != "":
        attributes["data-message-id"] = message_id
    return div(
        tw("min-w-0 shrink-0 [content-visibility:auto] [contain-intrinsic-size:auto_10rem]"),
        attributes,
        *children,
    )


@js
def MessageScrollerButton(
    *children,
    direction: str = "end",
    label: str = "Scroll to latest message",
):
    return button(
        tw(
            "absolute left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-2 "
            "rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium "
            "text-slate-700 shadow-lg transition-all hover:bg-slate-50 focus-visible:ring-2 "
            "focus-visible:ring-violet-300 data-[active=false]:pointer-events-none "
            "data-[active=false]:scale-95 data-[active=false]:opacity-0 "
            "data-[active=true]:scale-100 data-[active=true]:opacity-100 "
            "data-[direction=end]:bottom-4 data-[direction=start]:top-4"
        ),
        {
            "aria-label": label,
            "data-active": "false",
            "data-direction": direction,
            "data-slot": "message-scroller-button",
            "tabindex": "-1",
            "type": "button",
        },
        *children,
    )


@js
def MessageScrollerSpacer():
    return div(
        tw("pointer-events-none shrink-0"),
        {
            "aria-hidden": "true",
            "data-slot": "message-scroller-spacer",
            "style": "height: 0px",
        },
    )


@js
def scroller_node(child: object) -> Element:
    if isinstance(child, ProxyElement):
        return child.element
    if isinstance(child, Element):
        return child
    raise TypeError("Message scroller children must be elements.")


@js
class MessageScroller(Widget):
    def __init__(
        self,
        *children,
        label: str = "Messages",
        newest_first: bool = False,
        auto_scroll: bool = False,
        default_scroll_position: str = "end",
        scroll_edge_threshold: int = 8,
        scroll_previous_item_peek: int = 64,
    ):
        super().__init__()
        self.newest_first = newest_first
        self.auto_scroll = auto_scroll
        self.default_scroll_position = default_scroll_position
        self.scroll_edge_threshold = scroll_edge_threshold
        self.scroll_previous_item_peek = scroll_previous_item_peek
        self.mode = "following-bottom" if auto_scroll else "free-scrolling"
        self.default_scroll_applied = False
        self.autoscrolling = False
        self.autoscroll_timer = 0
        self._saved_scroll_top: float | None = None
        self.resize_observer: ResizeObserver | None = None
        self.spacer = ref(MessageScrollerSpacer())
        self.content = ref(MessageScrollerContent(*children, self.spacer))
        self.viewport = ref(MessageScrollerViewport(self.content, label=label))
        self.scroll_button = ref(
            MessageScrollerButton(
                "↑ Latest" if newest_first else "↓ Latest",
                direction="start" if newest_first else "end",
            )
        )
        self.set_data("auto-scroll", "true" if auto_scroll else "false")
        self.set_data("default-scroll", default_scroll_position)
        self.set_data("edge-threshold", str(scroll_edge_threshold))
        self.set_data("newest-first", "true" if newest_first else "false")
        self.set_data("peek", str(scroll_previous_item_peek))
        self.setAttribute("data-autoscrolling", "false")
        self.setAttribute("data-mode", self.mode)
        self.setAttribute("data-pending-scroll", "true")
        self.add(
            tw("relative flex size-full min-h-0 flex-col overflow-hidden"),
            {"data-slot": "message-scroller"},
            tag("style", SCROLLBAR_CSS + EFFECTS_CSS),
            self.viewport,
            self.scroll_button,
        )

    def initialize(self):
        self.newest_first = self.get_data("newest-first") == "true"
        self.auto_scroll = self.get_data("auto-scroll") == "true"
        stored_default = self.get_data("default-scroll")
        self.default_scroll_position = "end" if stored_default is None else stored_default
        threshold = self.get_data("edge-threshold")
        self.scroll_edge_threshold = 8 if threshold is None else int(threshold)
        peek = self.get_data("peek")
        self.scroll_previous_item_peek = 64 if peek is None else int(peek)
        stored_mode = self.getAttribute("data-mode")
        if stored_mode is None or stored_mode == "":
            self.mode = "following-bottom" if self.auto_scroll else "free-scrolling"
        else:
            self.mode = stored_mode
        self.default_scroll_applied = False
        self.autoscrolling = False
        self.autoscroll_timer = 0
        self._saved_scroll_top = None
        self._bind()
        self._observe_content()
        self._apply_default_scroll()

    def reconnected(self):
        saved = self._saved_scroll_top
        self._saved_scroll_top = None
        self._reset_autoscrolling_flag()
        self._observe_content()
        if self.mode == "following-bottom" and self.auto_scroll:
            self.scroll_to_latest()
        elif saved is not None:
            self.autoscrolling = True
            self.viewport.scrollTop = saved
            self._reset_autoscrolling_flag()
            self.update_scroll_button()
            sync_scroll_fade(self.viewport)

    def _bind(self) -> None:
        self.viewport.addEventListener("scroll", self.scrolled)
        self.viewport.addEventListener("wheel", self.user_intent)
        self.viewport.addEventListener("touchmove", self.user_intent)
        self.viewport.addEventListener("keydown", self.keydown_intent)
        self.scroll_button.addEventListener("click", self.jump_clicked)

    def _observe_content(self) -> None:
        observer = self.resize_observer
        if observer is not None:
            observer.disconnect()
        observer = ResizeObserver(self.content_resized)
        observer.observe(self.content)
        self.resize_observer = observer

    def disconnected(self):
        self._reset_autoscrolling_flag()
        observer = self.resize_observer
        if observer is not None:
            observer.disconnect()
            self.resize_observer = None

    def item_elements(self) -> list[HTMLElement]:
        found: list[HTMLElement] = []
        for child in self.content.children:
            if child is self.spacer:
                continue
            slot = child.getAttribute("data-slot") or ""
            if slot == "message-scroller-spacer":
                continue
            if isinstance(child, HTMLElement):
                found.append(child)
        return found

    def _item_count(self) -> int:
        return len(self.item_elements())

    def _ensure_spacer(self) -> Element:
        spacer = self.spacer
        if spacer.parentElement is not self.content:
            self.content.append(spacer)
        return spacer

    def _set_spacer_height(self, height: int) -> None:
        spacer = self._ensure_spacer()
        height = max(height, 0)
        spacer.style.height = str(height) + "px"

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self.setAttribute("data-mode", mode)

    def is_at_start(self) -> bool:
        return self.viewport.scrollTop <= self.scroll_edge_threshold

    def is_at_end(self) -> bool:
        remaining = (
            self.viewport.scrollHeight
            - self.viewport.scrollTop
            - self.viewport.clientHeight
        )
        return remaining <= self.scroll_edge_threshold

    def is_at_latest(self) -> bool:
        if self.newest_first:
            return self.is_at_start()
        return self.is_at_end()

    def _programmatic_scroll(self, top: float) -> None:
        top = max(top, 0)
        self.autoscrolling = True
        self.setAttribute("data-autoscrolling", "true")
        self.viewport.scrollTop = top
        self._saved_scroll_top = top
        if self.autoscroll_timer != 0:
            clearTimeout(self.autoscroll_timer)
        self.autoscroll_timer = setTimeout(self._clear_autoscrolling, 180)

    def _reset_autoscrolling_flag(self) -> None:
        if self.autoscroll_timer != 0:
            clearTimeout(self.autoscroll_timer)
            self.autoscroll_timer = 0
        self.autoscrolling = False
        self.setAttribute("data-autoscrolling", "false")

    def _clear_autoscrolling(self) -> None:
        self._reset_autoscrolling_flag()
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def scroll_to_latest(self):
        if self.auto_scroll:
            self._set_mode("following-bottom")
        if self.newest_first:
            self._programmatic_scroll(0)
        else:
            self._set_spacer_height(0)
            self._programmatic_scroll(self.viewport.scrollHeight)
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def scroll_to_start(self):
        self._programmatic_scroll(0)
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def scroll_to_end(self):
        self._programmatic_scroll(self.viewport.scrollHeight)
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def scroll_to_message(self, message_id: str) -> bool:
        if message_id == "":
            return False
        item = self.content.querySelector(
            "[data-slot=message-scroller-item][data-message-id='" + message_id + "']"
        )
        if not isinstance(item, HTMLElement):
            return False
        self._set_mode("free-scrolling")
        self._programmatic_scroll(item.offsetTop)
        self.update_scroll_button()
        return True

    def _last_anchor(self) -> HTMLElement | None:
        items = self.item_elements()
        index = len(items) - 1
        while index >= 0:
            if items[index].getAttribute("data-scroll-anchor") == "true":
                return items[index]
            index = index - 1
        return None

    def _clear_anchored_flags(self) -> None:
        for item in self.item_elements():
            item.removeAttribute("data-anchored")

    def _begin_anchor(self, item: HTMLElement) -> None:
        self._clear_anchored_flags()
        item.setAttribute("data-anchored", "true")
        self._set_mode("anchored-to-message")
        self._layout_anchor(item)

    def _layout_anchor(self, item: HTMLElement) -> None:
        peek = self.scroll_previous_item_peek
        viewport_height = self.viewport.clientHeight
        item_top = item.offsetTop
        item_height = item.offsetHeight
        desired = item_top - peek
        desired = max(desired, 0)
        room = viewport_height - peek - item_height
        room = max(room, 0)
        after = self.viewport.scrollHeight - self._spacer_height() - item_top - item_height
        after = max(after, 0)
        spacer_height = room - after
        if spacer_height <= 0 and self.auto_scroll and after > peek:
            self._clear_anchored_flags()
            self.scroll_to_latest()
            return
        self._set_spacer_height(spacer_height)
        self._programmatic_scroll(desired)
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def _spacer_height(self) -> int:
        spacer = self.content.querySelector("[data-slot=message-scroller-spacer]")
        if spacer is None:
            return 0
        return int(spacer.clientHeight)

    def _anchored_item(self) -> HTMLElement | None:
        item = self.content.querySelector(
            "[data-slot=message-scroller-item][data-anchored=true]"
        )
        if isinstance(item, HTMLElement):
            return item
        return None

    def _apply_default_scroll(self) -> None:
        position = self.default_scroll_position
        if self.newest_first or position == "start":
            self.scroll_to_start()
        elif position == "last-anchor":
            anchor = self._last_anchor()
            if anchor is None:
                self.scroll_to_end()
            else:
                fits = self.viewport.scrollHeight <= self.viewport.clientHeight + self.scroll_edge_threshold
                if fits:
                    self.scroll_to_end()
                else:
                    self._begin_anchor(anchor)
        else:
            self.scroll_to_end()
        if self.auto_scroll and self.is_at_latest():
            self._set_mode("following-bottom")
        self.default_scroll_applied = True
        self.removeAttribute("data-pending-scroll")
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def replace_messages(self, *children):
        follow_latest = self.is_at_latest() or self._item_count() == 0
        if self.mode == "free-scrolling" and self._item_count() > 0:
            follow_latest = False
        nodes: list[Element] = []
        for child in children:
            nodes.append(scroller_node(child))
        nodes.append(self._ensure_spacer())
        self.content.replaceChildren(*nodes)
        self._set_spacer_height(0)
        self._clear_anchored_flags()
        if self._item_count() == 0:
            self._apply_default_scroll()
            return
        if follow_latest:
            if self.default_scroll_position == "last-anchor":
                self._apply_default_scroll()
            else:
                self.scroll_to_latest()
            return
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def append_messages(self, *children):
        if len(children) == 0:
            return
        was_empty = self._item_count() == 0
        spacer = self._ensure_spacer()
        new_anchor: HTMLElement | None = None
        for child in children:
            node = scroller_node(child)
            self.content.insertBefore(node, spacer)
            if node.getAttribute("data-scroll-anchor") == "true" and isinstance(
                node, HTMLElement
            ):
                new_anchor = node
        if self.mode == "free-scrolling" and not was_empty:
            self.update_scroll_button()
            sync_scroll_fade(self.viewport)
            return
        if new_anchor is not None and not was_empty:
            self._begin_anchor(new_anchor)
            return
        if was_empty:
            self._apply_default_scroll()
            return
        if self.auto_scroll and (
            self.mode == "following-bottom" or self.is_at_latest()
        ):
            self.scroll_to_latest()
            return
        if self.mode == "anchored-to-message":
            anchored = self._anchored_item()
            if anchored is not None:
                self._layout_anchor(anchored)
                return
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def prepend_messages(self, *children):
        if len(children) == 0:
            return
        previous_height = self.viewport.scrollHeight
        previous_top = self.viewport.scrollTop
        first: Element | None = None
        items = self.item_elements()
        if len(items) > 0:
            first = items[0]
        nodes: list[Element] = []
        for child in children:
            nodes.append(scroller_node(child))
        index = len(nodes) - 1
        while index >= 0:
            node = nodes[index]
            if first is None:
                self.content.insertBefore(node, self._ensure_spacer())
            else:
                self.content.insertBefore(node, first)
            first = node
            index = index - 1
        added = self.viewport.scrollHeight - previous_height
        self._programmatic_scroll(previous_top + added)
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def update_scroll_button(self):
        active = not self.is_at_latest()
        self.scroll_button.setAttribute("data-active", "true" if active else "false")
        self.scroll_button.setAttribute("aria-hidden", "false" if active else "true")
        if active:
            self.scroll_button.removeAttribute("tabindex")
            self.scroll_button.inert = False
        else:
            self.scroll_button.setAttribute("tabindex", "-1")
            self.scroll_button.inert = True
        scrollable = ""
        if not self.is_at_start():
            scrollable = "start"
        if not self.is_at_end():
            if scrollable == "":
                scrollable = "end"
            else:
                scrollable = "start end"
        if scrollable == "":
            self.removeAttribute("data-scrollable")
        else:
            self.setAttribute("data-scrollable", scrollable)

    def user_intent(self, event: Event) -> None:
        if self.mode != "free-scrolling":
            self._set_mode("free-scrolling")
            self._clear_anchored_flags()
        self.update_scroll_button()

    def keydown_intent(self, event: KeyboardEvent) -> None:
        key = event.key
        if (
            key != "ArrowDown"
            and key != "ArrowUp"
            and key != "PageDown"
            and key != "PageUp"
            and key != "Home"
            and key != "End"
            and key != " "
        ):
            return
        self.user_intent(event)

    def scrolled(self, event: Event):
        if self.isConnected:
            self._saved_scroll_top = self.viewport.scrollTop
        if self.autoscrolling:
            return
        if self.auto_scroll and self.is_at_latest():
            self._set_mode("following-bottom")
        elif not self.is_at_latest() and self.mode == "following-bottom":
            self._set_mode("free-scrolling")
            self._clear_anchored_flags()
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def content_resized(self, entries: object, observer: object) -> None:
        if self.mode == "anchored-to-message":
            anchored = self._anchored_item()
            if anchored is not None:
                self._layout_anchor(anchored)
                return
        if self.mode == "following-bottom" and self.auto_scroll:
            self.scroll_to_latest()
            return
        self.update_scroll_button()
        sync_scroll_fade(self.viewport)

    def jump_clicked(self, event: Event):
        self.scroll_to_latest()
