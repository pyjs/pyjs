from dataclasses import dataclass

from pyjs.web.dom import Element
from pyjs.web.domx import div, p, span, tag, tw
from pyjs.web.ssr import render_html, write_html_fd


@dataclass(frozen=True)
class LogEntry:
    log_id: str
    occurred_at: str
    severity: str
    service: str
    message: str
    trace_id: str
    task_id: str
    repeated: int
    attributes: list[tuple[str, str]]


def logs(count: int = 320) -> list[LogEntry]:
    result: list[LogEntry] = []
    for index in range(count):
        severity = "error" if index % 17 == 0 else (
            "warning" if index % 7 == 0 else "info"
        )
        result.append(
            LogEntry(
                log_id=f"log-{index:05}",
                occurred_at=f"2026-09-02T03:{index % 60:02}:17.125Z",
                severity=severity,
                service=f"application-{index % 6}",
                message=(
                    "Handled request with unicode café 🙂 and escaped <payload> "
                    f"for route /projects/{index % 19}"
                ),
                trace_id=f"trace-{index // 4:04}",
                task_id=f"task-{index % 12:02}",
                repeated=index % 5 + 1,
                attributes=[
                    ("method", "GET" if index % 3 else "POST"),
                    ("status", str(500 if severity == "error" else 200)),
                    ("region", "iad" if index % 2 else "fra"),
                ],
            )
        )
    return result


def log_row(value: LogEntry) -> Element:
    attributes: list[Element] = []
    for name, item in value.attributes:
        attributes.append(
            span(
                tw("attribute"),
                tag("code", tw("attribute-name"), name),
                "=",
                tag("code", tw("attribute-value"), item),
            )
        )
    return tag(
        "article",
        tw("log-row grid border-b"),
        {
            "data-log-id": value.log_id,
            "data-severity": value.severity,
            "data-service": value.service,
            "data-trace-id": value.trace_id,
        },
        tag("time", tw("timestamp"), value.occurred_at),
        span(tw("severity badge"), value.severity),
        span(tw("service"), value.service),
        p(tw("message"), value.message),
        div(tw("attributes flex"), *attributes),
        span(tw("task"), value.task_id),
        span(tw("repeated"), "×", str(value.repeated)),
    )


def logs_page(values: list[LogEntry]) -> Element:
    rows: list[Element] = []
    for value in values:
        rows.append(log_row(value))
    return div(
        tw("log-explorer"),
        {"data-log-count": str(len(values))},
        *rows,
    )


def render_logs(values: list[LogEntry]) -> str:
    return render_html(logs_page(values))


def write_logs(values: list[LogEntry], descriptor: int) -> int:
    return write_html_fd(logs_page(values), descriptor)
