"""Client behavior for the live Python-authored performance UI."""
from pyjs import js
from pyjs.web.dom import Element, document, window
from pyjs.web.events import Event
from pyjs.web.html import HTMLSelectElement


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
        self.update(Event("change"))

    def choose_snapshot(self, event: Event):
        window.location.href = "?run=" + self.snapshot.value

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
            for cell in cells:
                is_baseline = cell.getAttribute("data-target") == "cpython"
                cell.setAttribute("data-baseline", "true" if is_baseline else "false")
                value = cell.getAttribute("data-" + metric)
                display = cell.querySelector(".measurement")
                assert isinstance(display, Element)
                for ratio in cell.querySelectorAll(".ratio"):
                    ratio.removeAttribute("data-comparison")
                    text = ratio.querySelector(".ratio-value")
                    assert isinstance(text, Element)
                    text.textContent = "—"
                if value is None or value == "":
                    display.textContent = "—"
                    continue
                number = float(value)
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


def main():
    if document.querySelector("#metric") is not None:
        Controls()
