from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import div, tag, tw
from pyjs.web.ui.streaming_list import StreamingList

__all__ = ["StreamingLog"]


@js
def _log_rows(lines: tuple[str, ...], wrap: bool = False) -> list[Element]:
    rows: list[Element] = []
    if wrap:
        row_class = tw(
            "min-w-0 whitespace-pre-wrap break-words px-3 py-0.5 "
            "font-mono text-xs leading-5 text-slate-200"
        )
    else:
        row_class = tw(
            "min-w-max whitespace-pre px-3 py-0.5 font-mono text-xs "
            "leading-5 text-slate-200"
        )
    for line in lines:
        rows.append(
            div(
                row_class,
                {"data-slot": "streaming-log-line"},
                line,
            )
        )
    return rows


@js
class StreamingLog(StreamingList):
    """Display a bounded, pausable, follow-tail stream of plain-text lines."""

    def __init__(
        self,
        *lines: str,
        label: str = "Live log output",
        max_lines: int = 2000,
        wrap: bool = False,
    ):
        super().__init__(
            *_log_rows(lines, wrap),
            label=label,
            max_items=max_lines,
        )
        self.wrap = wrap
        self.set_data("wrap", "true" if wrap else "false")
        tag(
            self,
            tw(
                "overflow-hidden rounded-md border border-slate-800 bg-slate-950 "
                "text-slate-100 "
                "[&_[data-slot=message-scroller-content]]:gap-0 "
                "[&_[data-slot=message-scroller-content]]:p-0 "
                "[&_[data-slot=streaming-list-status]]:text-slate-400 "
                "[&_[data-slot=streaming-list-pause]]:border-slate-700 "
                "[&_[data-slot=streaming-list-pause]]:bg-slate-900 "
                "[&_[data-slot=streaming-list-pause]]:text-slate-200"
            ),
            {"data-slot": "streaming-log"},
        )

    def initialize(self):
        super().initialize()
        self.wrap = self.get_data("wrap") == "true"

    def append_live(self, *lines: str):
        self._append_live_elements(*_log_rows(lines, self.wrap))

    def add_history(self, *lines: str):
        super().add_history(*_log_rows(lines, self.wrap))

    def replace(self, *lines: str):
        super().replace(*_log_rows(lines, self.wrap))
