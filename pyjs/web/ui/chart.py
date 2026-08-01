from pyjs import js
from pyjs.web.domx import div, tag, tw


@js
def BarChart(
    values: list[int],
    labels: list[str] | None = None,
    *,
    label: str = "Bar chart",
    height: int = 180,
):
    resolved_labels: list[str] = []
    if labels is not None:
        resolved_labels = labels
    maximum = 1
    for value in values:
        if value > maximum:
            maximum = value
    chart = tag(
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
        bar_height = round(values[index] / maximum * (height - 30))
        x = 10 + index * bar_width
        y = height - 20 - bar_height
        bar_label = str(values[index])
        if index < len(resolved_labels):
            bar_label = resolved_labels[index] + ": " + str(values[index])
        chart.append(
            tag(
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
