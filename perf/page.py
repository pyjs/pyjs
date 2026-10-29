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
        assert isinstance(metric, Element)
        self.metric = "warm"
        metric.addEventListener("click", self.choose_metric)
        snapshot = document.querySelector("#snapshot")
        assert isinstance(snapshot, HTMLSelectElement)
        self.snapshot = snapshot
        self.snapshot.addEventListener("change", self.choose_snapshot)
        self.source_request = 0
        for table in document.querySelectorAll(".comparison-table"):
            table.addEventListener("click", self.choose_source)
            table.addEventListener("keydown", self.source_key)
        self.update(Event("change"))

    def choose_snapshot(self, event: Event):
        window.location.href = "?run=" + self.snapshot.value if self.snapshot.value else window.location.pathname

    def choose_metric(self, event: Event):
        target = event.target
        if not isinstance(target, Element):
            return
        button = target.closest("button[data-metric]")
        if button is None:
            return
        self.metric = button.getAttribute("data-metric") or "warm"
        for item in document.querySelectorAll("#metric button"):
            item.setAttribute("aria-pressed", "true" if item == button else "false")
        self.update(event)

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

    def render_source(self, code: Element, text: str, ranges: str):
        code.textContent = ""
        lines = text.split("\n")
        starts: list[int] = []
        ends: list[int] = []
        try:
            for item in ranges.split(";"):
                if item:
                    pair = item.split(":")
                    start, end = int(pair[0]), int(pair[1])
                    if start < 0 or end <= start or end > len(lines) or (ends and start < ends[-1]):
                        raise ValueError("Invalid source range")
                    starts.append(start)
                    ends.append(end)
        except Exception:
            starts = []
            ends = []
        if not starts:
            plain = document.createElement("pre")
            plain.textContent = text
            code.appendChild(plain)
            return
        cursor = 0
        for index in range(len(starts) + 1):
            boundary = starts[index] if index < len(starts) else len(lines)
            if cursor < boundary:
                self.source_block(code, lines, cursor, boundary, False)
            if index < len(starts):
                self.source_block(code, lines, starts[index], ends[index], True)
                cursor = ends[index]

    def source_block(self, code: Element, lines: list[str], start: int, end: int, algorithm: bool):
        block = document.createElement("details")
        block.setAttribute("class", "code-fold")
        block.setAttribute("data-algorithm", "true" if algorithm else "false")
        if algorithm:
            block.setAttribute("open", "")
        heading = document.createElement("summary")
        heading.textContent = ("Algorithm" if algorithm else "Runtime / scaffolding") + " · lines " + str(start + 1) + "–" + str(end)
        content = document.createElement("pre")
        content.textContent = "\n".join(lines[start:end]) + ("\n" if end < len(lines) else "")
        block.appendChild(heading)
        block.appendChild(content)
        code.appendChild(block)

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
        if not panel.hasAttribute("hidden") and cell.hasAttribute("data-source-selected"):
            self.close_sources()
            return
        self.close_sources()
        request = self.source_request
        panel.removeAttribute("hidden")
        button.setAttribute("aria-expanded", "true")
        cell.setAttribute("data-source-selected", "true")
        cue = cell.querySelector(".source-cue")
        if cue is not None:
            cue.textContent = "Showing code ↓"
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
        self.render_source(code, source.textContent or "", "")
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
                self.render_source(code, text, response.headers.get("X-PyJS-Algorithm-Ranges") or "")
                status.textContent = ""
        except Exception:
            if request == self.source_request:
                status.textContent = "Could not load generated code. The artifact may have been removed; close and reopen to retry."

    def update(self, event: Event):
        metric = self.metric
        for cell in document.querySelectorAll("[data-summary-target]"):
            label = cell.querySelector(".category-value")
            assert isinstance(label, Element)
            label.textContent = cell.getAttribute("data-label-" + metric) or "—"
            cell.setAttribute("style", cell.getAttribute("data-style-" + metric) or "")
        for heading in document.querySelectorAll(".comparison-table thead th[data-target]"):
            heading.setAttribute("data-baseline", "true" if heading.getAttribute("data-target") == "cpython" else "false")
        rows = document.querySelectorAll(".comparison-table tbody tr[data-case]")
        for row in rows:
            cells = row.querySelectorAll("td[data-target]")
            smallest = 0.0
            largest = 0.0
            for cell in cells:
                value = cell.getAttribute("data-" + metric) or ""
                if value != "" and cell.getAttribute("data-target") != "cpython":
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
                for note in cell.querySelectorAll(".code-gzip"):
                    if metric == "size" and value != "" and note.textContent:
                        note.removeAttribute("hidden")
                    else:
                        note.setAttribute("hidden", "")
                for ratio in cell.querySelectorAll(".ratio"):
                    ratio.removeAttribute("data-comparison")
                    text = ratio.querySelector(".ratio-value")
                    assert isinstance(text, Element)
                    text.textContent = "—"
                if value == "":
                    display.textContent = "—"
                    continue
                number = float(value)
                if not is_baseline and number > 0 and largest > smallest and smallest > 0:
                    heat = (math.log(number) - math.log(smallest)) / (math.log(largest) - math.log(smallest))
                    cell.setAttribute("data-heat", str(heat))
                    cell.setAttribute("style", "background-color:hsl(" + str(round(155 - 135 * heat, 2)) + " 32% 18%)")
                if metric == "memory":
                    display.textContent = str(round(number / 1024, 2)) + " MiB"
                elif metric == "compile":
                    display.textContent = str(round(number, 3)) + " s"
                elif metric == "size":
                    display.textContent = str(round(number / 1024, 2)) + " KiB"
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
                        if metric == "size":
                            suffix = " smaller"
                        factor = round(float(reference) / number, 2)
                        text.textContent = "≈ same" if factor == 1 else str(factor) + "×" + suffix
                        ratio.setAttribute("data-comparison", "lower")
                    else:
                        suffix = " more memory" if metric == "memory" else " slower"
                        if metric == "size":
                            suffix = " larger"
                        factor = round(number / float(reference), 2)
                        text.textContent = "≈ same" if factor == 1 else str(factor) + "×" + suffix
                        ratio.setAttribute("data-comparison", "higher")


def main():
    if document.querySelector("#metric") is not None:
        Controls()
