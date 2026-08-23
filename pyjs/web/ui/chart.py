from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import div, ref, svg_tag, tw
from pyjs.web.ui import Widget


@js
def chart_labels(values: list[int], labels: list[str] | None) -> list[str]:
    resolved: list[str] = []
    for index in range(len(values)):
        if labels is not None and index < len(labels):
            resolved.append(labels[index])
        else:
            resolved.append(str(index + 1))
    return resolved


@js
def chart_value_labels(
    values: list[int],
    labels: list[str] | None,
) -> list[str]:
    resolved: list[str] = []
    for index in range(len(values)):
        if labels is not None and index < len(labels):
            resolved.append(labels[index])
        else:
            resolved.append(str(values[index]))
    return resolved


@js
def chart_annotation_labels(
    values: list[int],
    labels: list[str] | None,
) -> list[str]:
    resolved: list[str] = []
    for index in range(len(values)):
        if labels is not None and index < len(labels):
            resolved.append(labels[index])
        else:
            resolved.append("")
    return resolved


@js
def chart_bounds(values: list[int]) -> tuple[int, int]:
    if not values:
        return 0, 1
    minimum = values[0]
    maximum = values[0]
    for value in values:
        if value < minimum:
            minimum = value
        if value > maximum:
            maximum = value
    if minimum == maximum:
        minimum = 0
        if maximum == 0:
            maximum = 1
    return minimum, maximum


@js
def BarChart(
    values: list[int],
    labels: list[str] | None = None,
    *,
    label: str = "Bar chart",
    height: int = 180,
):
    resolved_labels = chart_labels(values, labels)
    minimum, maximum = chart_bounds(values)
    if minimum > 0:
        minimum = 0
    chart = svg_tag(
        "svg",
        tw("h-auto w-full overflow-visible"),
        {
            "aria-label": label,
            "data-slot": "chart",
            "role": "img",
            "viewBox": "0 0 100 " + str(height),
        },
    )
    if len(values) == 0:
        return chart
    bar_width = 80 / len(values)
    for index in range(len(values)):
        bar_height = round(
            (values[index] - minimum) / (maximum - minimum) * (height - 30)
        )
        x = 10 + index * bar_width
        y = height - 20 - bar_height
        bar_label = resolved_labels[index] + ": " + str(values[index])
        chart.append(
            svg_tag(
                "rect",
                {
                    "aria-label": bar_label,
                    "data-slot": "chart-bar",
                    "fill": "#0f172a",
                    "height": str(bar_height),
                    "role": "graphics-symbol",
                    "rx": "1",
                    "width": str(bar_width - 2),
                    "x": str(x),
                    "y": str(y),
                },
            )
        )
    return div(tw("w-full overflow-hidden"), {"data-slot": "chart-container"}, chart)


@js
class LineChart(Widget):
    def __init__(
        self,
        values: list[int],
        labels: list[str] | None = None,
        *,
        color: str = "#0f172a",
        grid_color: str = "#e2e8f0",
        label: str = "Line chart",
        value_labels: list[str] | None = None,
        annotation_labels: list[str] | None = None,
        annotation_color: str = "#d97706",
    ):
        super().__init__()
        self.set_data("chart-color", color)
        self.set_data("grid-color", grid_color)
        self.set_data("annotation-color", annotation_color)
        self.svg = ref(
            svg_tag(
                "svg",
                tw("h-auto w-full overflow-visible"),
                {
                    "aria-label": label,
                    "data-slot": "chart",
                    "role": "img",
                    "viewBox": "0 0 1000 400",
                },
            )
        )
        self.graph = ref(
            div(
                tw("w-full overflow-hidden"),
                {"data-slot": "chart-container"},
                self.svg,
            )
        )
        self.add(self.graph)
        self.set_points(values, labels, value_labels, annotation_labels)

    def chart(self) -> Element:
        return self.svg

    def set_points(
        self,
        values: list[int],
        labels: list[str] | None = None,
        value_labels: list[str] | None = None,
        annotation_labels: list[str] | None = None,
    ):
        labels = chart_labels(values, labels)
        value_labels = chart_value_labels(values, value_labels)
        annotation_labels = chart_annotation_labels(values, annotation_labels)
        minimum, maximum = chart_bounds(values)
        color = self.get_data("chart-color")
        grid_color = self.get_data("grid-color")
        annotation_color = self.get_data("annotation-color")
        if color is None or grid_color is None or annotation_color is None:
            raise ValueError("Line chart colors are missing from the DOM.")
        children: list[Element] = []
        for y in (40, 200, 360):
            children.append(
                svg_tag(
                    "line",
                    {
                        "aria-hidden": "true",
                        "stroke": grid_color,
                        "x1": "40",
                        "x2": "960",
                        "y1": str(y),
                        "y2": str(y),
                    },
                )
            )
        if not values:
            self.chart().replaceChildren(*children)
            return
        path = ""
        point_count = len(values)
        for index in range(point_count):
            if point_count == 1:
                x = 500
            else:
                x = 40 + index * 920 // (point_count - 1)
            y = 360 - (values[index] - minimum) * 320 // (maximum - minimum)
            path += ("M" if index == 0 else " L") + str(x) + " " + str(y)
            annotation_label = annotation_labels[index]
            if annotation_label:
                children.append(
                    svg_tag(
                        "line",
                        {
                            "aria-label": (
                                labels[index] + ": " + annotation_label
                            ),
                            "data-annotation-label": annotation_label,
                            "data-label": labels[index],
                            "data-slot": "chart-annotation",
                            "role": "graphics-symbol",
                            "stroke": annotation_color,
                            "stroke-dasharray": "12 8",
                            "stroke-width": "4",
                            "x1": str(x),
                            "x2": str(x),
                            "y1": "40",
                            "y2": "360",
                        },
                    )
                )
            children.append(
                svg_tag(
                    "circle",
                    {
                        "aria-label": labels[index] + ": " + value_labels[index],
                        "fill": color,
                        "data-label": labels[index],
                        "data-slot": "chart-point",
                        "data-value": str(values[index]),
                        "data-value-label": value_labels[index],
                        "data-annotation-label": annotation_label,
                        "r": "7",
                        "role": "graphics-symbol",
                        "cx": str(x),
                        "cy": str(y),
                    },
                )
            )
        children.insert(
            3,
            svg_tag(
                "path",
                {
                    "fill": "none",
                    "d": path,
                    "data-slot": "chart-line",
                    "stroke-linecap": "round",
                    "stroke-linejoin": "round",
                    "stroke": color,
                    "stroke-width": "8",
                },
            ),
        )
        self.chart().replaceChildren(*children)

    def append_point(
        self,
        value: int,
        label: str,
        max_points: int = 60,
        value_label: str = "",
        annotation_label: str = "",
    ):
        if max_points < 1:
            raise ValueError("A line chart must retain at least one point.")
        values: list[int] = []
        labels: list[str] = []
        value_labels: list[str] = []
        annotation_labels: list[str] = []
        for point in self.chart().children:
            if point.getAttribute("data-slot") == "chart-point":
                point_value = point.getAttribute("data-value")
                point_label = point.getAttribute("data-label")
                point_value_label = point.getAttribute("data-value-label")
                point_annotation_label = point.getAttribute(
                    "data-annotation-label"
                )
                if (
                    point_value is not None
                    and point_label is not None
                    and point_value_label is not None
                    and point_annotation_label is not None
                ):
                    values.append(int(point_value))
                    labels.append(point_label)
                    value_labels.append(point_value_label)
                    annotation_labels.append(point_annotation_label)
        values.append(value)
        labels.append(label)
        value_labels.append(value_label if value_label else str(value))
        annotation_labels.append(annotation_label)
        while len(values) > max_points:
            values.pop(0)
            labels.pop(0)
            value_labels.pop(0)
            annotation_labels.pop(0)
        self.set_points(values, labels, value_labels, annotation_labels)
