"""Client behavior for the live Python-authored performance UI."""
import math

from pyjs import js
from pyjs.web.dom import Element, document, window
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement, HTMLSelectElement
from pyjs.web.network import fetch


@js
class Controls:
    def __init__(self):
        metric = document.querySelector("#metric")
        group = document.querySelector("#group")
        case = document.querySelector("#workload")
        assert isinstance(metric, HTMLSelectElement)
        assert isinstance(group, HTMLSelectElement)
        assert isinstance(case, HTMLSelectElement)
        self.metric = metric
        self.group = group
        self.case = case
        self.metric.addEventListener("change", self.update)
        self.group.addEventListener("change", self.update)
        self.case.addEventListener("change", self.update)
        snapshot = document.querySelector("#snapshot")
        assert isinstance(snapshot, HTMLSelectElement)
        self.snapshot = snapshot
        self.snapshot.addEventListener("change", self.choose_snapshot)
        self.source_request = 0
        table = document.querySelector(".comparison-table")
        assert isinstance(table, Element)
        table.addEventListener("click", self.choose_source)
        table.addEventListener("keydown", self.source_key)
        window.addEventListener("resize", self.update)
        self.update(Event("change"))

    def choose_snapshot(self, event: Event):
        window.location.href = "?run=" + self.snapshot.value if self.snapshot.value else window.location.pathname

    def size_sources(self):
        scroller = document.querySelector(".table-scroll")
        assert isinstance(scroller, Element)
        scroller.setAttribute("style", "--source-width:" + str(scroller.clientWidth) + "px")

    def close_sources(self, restore_focus: bool = False):
        self.source_request += 1
        for button in document.querySelectorAll('[data-source-button][aria-expanded="true"]'):
            button.setAttribute("aria-expanded", "false")
            if restore_focus and isinstance(button, HTMLElement):
                button.focus()
        for panel in document.querySelectorAll(".source-row"):
            panel.setAttribute("hidden", "")
        for cell in document.querySelectorAll("[data-source-selected]"):
            cell.removeAttribute("data-source-selected")
            cue = cell.querySelector(".source-cue")
            if cue is not None:
                cue.textContent = "View code ↓"

    def source_key(self, event: Event):
        if isinstance(event, KeyboardEvent) and event.key == "Escape":
            self.close_sources(True)

    async def choose_source(self, event: Event):
        target = event.target
        if not isinstance(target, Element) or target.closest("a") is not None:
            return
        if target.closest("[data-close-source]") is not None:
            self.close_sources(True)
            return
        cell = target.closest("td[data-target], th[scope=row]")
        if cell is None:
            return
        button = cell.querySelector("[data-source-button]")
        row = cell.closest("tr[data-case]")
        if button is None or row is None:
            return
        panel = document.getElementById(button.getAttribute("aria-controls") or "")
        assert isinstance(panel, Element)
        runtime = cell.getAttribute("data-target") or "cpython"
        if not panel.hasAttribute("hidden") and panel.getAttribute("data-runtime") == runtime:
            self.close_sources()
            return
        self.close_sources()
        request = self.source_request
        panel.removeAttribute("hidden")
        panel.setAttribute("data-runtime", runtime)
        button.setAttribute("aria-expanded", "true")
        cell.setAttribute("data-source-selected", "true")
        cue = cell.querySelector(".source-cue")
        if cue is not None:
            cue.textContent = "Showing code ↓"
        # A filtered table has fewer columns; the expansion must span just those.
        content = panel.querySelector("td")
        assert isinstance(content, Element)
        content.setAttribute("colspan", "8" if self.group.value == "all" else "4")
        self.size_sources()
        title = panel.querySelector(".target-title")
        code = panel.querySelector(".target-code")
        status = panel.querySelector(".source-status")
        link = panel.querySelector(".source-download")
        source = document.getElementById("source-" + (row.getAttribute("data-case") or "") + "-" + runtime)
        assert isinstance(title, Element)
        assert isinstance(code, Element)
        assert isinstance(status, Element)
        assert isinstance(link, Element)
        assert isinstance(source, Element)
        title.textContent = button.getAttribute("data-source-label") or "CPython · shared Python source"
        status.textContent = ""
        link.setAttribute("hidden", "")
        link.removeAttribute("href")
        code.textContent = source.textContent
        url = source.getAttribute("data-url") or ""
        if url == "":
            return
        link.setAttribute("href", url)
        link.removeAttribute("hidden")
        code.textContent = ""
        status.textContent = "Loading generated code…"
        try:
            response = await fetch(url)
            if not response.ok:
                raise ValueError("Artifact unavailable")
            text = await response.text()
            if request == self.source_request:
                code.textContent = text
                status.textContent = ""
        except Exception:
            if request == self.source_request:
                status.textContent = "Could not load generated code. The artifact may have been removed; close and reopen to retry."

    def update(self, event: Event):
        metric = "warm"
        group = "all"
        selected = "all"
        if isinstance(self.metric, HTMLSelectElement):
            metric = self.metric.value
        if isinstance(self.group, HTMLSelectElement):
            group = self.group.value
        if isinstance(self.case, HTMLSelectElement):
            selected = self.case.value
        table = document.querySelector(".comparison-table")
        assert isinstance(table, Element)
        table.setAttribute("data-view", group)
        for item in table.querySelectorAll("[data-group]"):
            if group == "all" or item.getAttribute("data-group") == "python" or item.getAttribute("data-group") == group:
                item.removeAttribute("hidden")
            else:
                item.setAttribute("hidden", "")
        for heading in table.querySelectorAll("thead th[data-target]"):
            heading.setAttribute("data-baseline", "true" if heading.getAttribute("data-target") == "cpython" else "false")
        rows = table.querySelectorAll("tbody tr[data-case]")
        for row in rows:
            case = row.getAttribute("data-case")
            if selected == "all" or selected == case:
                row.removeAttribute("hidden")
            else:
                row.setAttribute("hidden", "")
            cells = row.querySelectorAll("td[data-target]")
            smallest = 0.0
            largest = 0.0
            for cell in cells:
                value = cell.getAttribute("data-" + metric) or ""
                if value != "" and not cell.hasAttribute("hidden") and cell.getAttribute("data-target") != "cpython":
                    number = float(value)
                    if number > 0:
                        if smallest == 0 or number < smallest:
                            smallest = number
                        if number > largest:
                            largest = number
            for cell in cells:
                cell.removeAttribute("style")
                cell.removeAttribute("data-heat")
                is_baseline = cell.getAttribute("data-target") == "cpython"
                cell.setAttribute("data-baseline", "true" if is_baseline else "false")
                value = cell.getAttribute("data-" + metric) or ""
                display = cell.querySelector(".measurement")
                assert isinstance(display, Element)
                for ratio in cell.querySelectorAll(".ratio"):
                    ratio.removeAttribute("data-comparison")
                    text = ratio.querySelector(".ratio-value")
                    assert isinstance(text, Element)
                    text.textContent = "—"
                if value == "":
                    display.textContent = "—"
                    continue
                number = float(value)
                if not is_baseline and number > 0 and largest > smallest and smallest > 0 and not cell.hasAttribute("hidden"):
                    heat = (math.log(number) - math.log(smallest)) / (math.log(largest) - math.log(smallest))
                    cell.setAttribute("data-heat", str(heat))
                    cell.setAttribute("style", "background-color:hsl(" + str(round(155 - 135 * heat, 2)) + " 32% 18%)")
                if metric == "memory":
                    display.textContent = str(round(number / 1024, 2)) + " MiB"
                elif metric == "compile":
                    display.textContent = str(round(number, 3)) + " s"
                else:
                    display.textContent = str(round(number * 1000, 3)) + " ms"
                for ratio in cell.querySelectorAll(".ratio"):
                    reference = ""
                    for other in cells:
                        if other.getAttribute("data-target") == ratio.getAttribute("data-reference"):
                            reference = other.getAttribute("data-" + metric) or ""
                    text = ratio.querySelector(".ratio-value")
                    assert isinstance(text, Element)
                    if reference == "" or number <= 0 or float(reference) <= 0:
                        continue
                    if number == float(reference):
                        text.textContent = "same"
                    elif number < float(reference):
                        suffix = " less memory" if metric == "memory" else " faster"
                        factor = round(float(reference) / number, 2)
                        text.textContent = "≈ same" if factor == 1 else str(factor) + "×" + suffix
                        ratio.setAttribute("data-comparison", "lower")
                    else:
                        suffix = " more memory" if metric == "memory" else " slower"
                        factor = round(number / float(reference), 2)
                        text.textContent = "≈ same" if factor == 1 else str(factor) + "×" + suffix
                        ratio.setAttribute("data-comparison", "higher")
        # Keep an expanded source attached to the visible row and selected pair.
        for panel in table.querySelectorAll(".source-row:not([hidden])"):
            runtime = panel.getAttribute("data-runtime") or "cpython"
            allowed = (group == "all" or runtime == "cpython" or
                       (group == "js" and (runtime == "javascript" or runtime == "pyjs-js")) or
                       (group == "native" and (runtime == "rust" or runtime == "pyjs-llvm")) or
                       (group == "jvm" and (runtime == "java" or runtime == "pyjs-jvm")))
            if not allowed or (selected != "all" and panel.getAttribute("data-source-case") != selected):
                self.close_sources()
            else:
                content = panel.querySelector("td")
                assert isinstance(content, Element)
                content.setAttribute("colspan", "8" if group == "all" else "4")
        self.size_sources()


def main():
    if document.querySelector("#metric") is not None:
        Controls()
