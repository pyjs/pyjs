"""Client behavior for the live Python-authored performance UI."""
from pyjs import js
from pyjs.web.dom import Element, document, window
from pyjs.web.events import Event
from pyjs.web.html import HTMLSelectElement


@js
class Controls:
    def __init__(self):
        metric = document.querySelector("#metric")
        baseline = document.querySelector("#baseline")
        case = document.querySelector("#workload")
        assert isinstance(metric, HTMLSelectElement)
        assert isinstance(baseline, HTMLSelectElement)
        assert isinstance(case, HTMLSelectElement)
        self.metric = metric
        self.baseline = baseline
        self.case = case
        self.metric.addEventListener("change", self.update)
        self.baseline.addEventListener("change", self.update)
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
        baseline = "cpython"
        selected = "all"
        if isinstance(self.metric, HTMLSelectElement):
            metric = self.metric.value
        if isinstance(self.baseline, HTMLSelectElement):
            baseline = self.baseline.value
        if isinstance(self.case, HTMLSelectElement):
            selected = self.case.value
        for heading in document.querySelectorAll("thead th[data-target]"):
            heading.setAttribute("data-baseline", "true" if heading.getAttribute("data-target") == baseline else "false")
        rows = document.querySelectorAll("tbody tr[data-case]")
        for row in rows:
            case = row.getAttribute("data-case")
            if selected == "all" or selected == case:
                row.removeAttribute("hidden")
            else:
                row.setAttribute("hidden", "")
            cells = row.querySelectorAll("td[data-target]")
            reference = ""
            for cell in cells:
                if cell.getAttribute("data-target") == baseline:
                    reference = cell.getAttribute("data-" + metric) or ""
            for cell in cells:
                is_baseline = cell.getAttribute("data-target") == baseline
                cell.setAttribute("data-baseline", "true" if is_baseline else "false")
                cell.removeAttribute("data-comparison")
                value = cell.getAttribute("data-" + metric)
                display = cell.querySelector(".measurement")
                ratio = cell.querySelector(".ratio")
                assert isinstance(display, Element)
                assert isinstance(ratio, Element)
                ratio.textContent = "—"
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
                if reference != "" and number > 0 and float(reference) > 0:
                    if is_baseline:
                        ratio.textContent = "baseline"
                    elif number == float(reference):
                        ratio.textContent = "same as baseline"
                    elif number < float(reference):
                        suffix = " less memory" if metric == "memory" else " faster"
                        ratio.textContent = str(round(float(reference) / number, 2)) + "×" + suffix
                        cell.setAttribute("data-comparison", "lower")
                    else:
                        suffix = " more memory" if metric == "memory" else " slower"
                        ratio.textContent = str(round(number / float(reference), 2)) + "×" + suffix
                        cell.setAttribute("data-comparison", "higher")


def main():
    if document.querySelector("#metric") is not None:
        Controls()
