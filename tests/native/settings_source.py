from dataclasses import dataclass

from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, p, span, tag, tw
from pyjs.web.ssr import render_html, write_html_fd


@dataclass(frozen=True)
class Setting:
    custom_id: str
    name: str
    description: str
    risk: str
    changed: bool
    changed_text: str
    restart: bool
    restart_text: str
    search: str
    values: list[tuple[str, str]]
    guidance: str
    extra: str


def settings() -> list[Setting]:
    result: list[Setting] = []
    for index in range(48):
        changed = index % 5 == 0
        restart = index % 7 == 0
        risk = "high" if index % 11 == 0 else (
            "caution" if index % 7 == 0 else "routine"
        )
        result.append(
            Setting(
                custom_id=f"ce{index + 1}",
                name=f"work_mem_{index}",
                description="Memory available to query operations & sorts.",
                risk=risk,
                changed=changed,
                changed_text="true" if changed else "false",
                restart=restart,
                restart_text="true" if restart else "false",
                search=f"work_mem_{index} resource usage memory",
                values=[
                    ("Current", "4096 kB"),
                    ("Default", "4096"),
                    ("Reset", "4096"),
                    ("Source", "default"),
                    ("Type", "integer"),
                    ("Range", "64 – 2147483647"),
                ],
                guidance="Estimate peak concurrent sorts and hashes.",
                extra=(
                    "Review workload concurrency before increasing this value."
                    if index % 3 == 0
                    else ""
                ),
            )
        )
    return result


def badge(text: str, variant: str) -> Element:
    return span(
        tw("badge px-2 text-xs"),
        {"data-variant": variant},
        text,
    )


class BenchmarkSetting(CustomElement):
    def __init__(self, setting: Setting):
        super().__init__()
        tag(
            self,
            tw("custom setting-guidance"),
            p(tw("guidance text-sm"), setting.guidance),
            p(tw("extra text-xs"), setting.extra)
            if setting.extra
            else span(),
        )


def setting_row(setting: Setting) -> Element:
    badges: list[Element] = [badge(setting.risk, "outline")]
    if setting.changed:
        badges.append(badge("non-default", "secondary"))
    if setting.restart:
        badges.append(badge("restart pending", "default"))

    values: list[Element] = []
    for label, value in setting.values:
        values.append(
            div(
                p(tw("label text-xs"), label),
                p(tw("value text-sm"), value),
            )
        )

    return tag(
        "details",
        tw("setting border-b"),
        {
            "data-setting": setting.search,
            "data-risk": setting.risk,
            "data-changed": setting.changed_text,
            "data-restart": setting.restart_text,
        },
        tag(
            "summary",
            tw("summary px-4 py-3"),
            div(
                tw("heading flex"),
                div(
                    tag(
                        "code",
                        tw("name font-semibold"),
                        setting.name,
                    ),
                    p(
                        tw("description text-xs"),
                        setting.description,
                    ),
                ),
                div(tw("badges flex"), *badges),
            ),
        ),
        div(
            tw("body grid"),
            div(tw("values grid"), *values),
            BenchmarkSetting(setting),
        ),
    )


def settings_page(values: list[Setting]) -> Element:
    rows: list[Element] = []
    for setting in values:
        rows.append(setting_row(setting))
    return div(
        tw("catalog rounded"),
        {"data-settings": ""},
        *rows,
    )


def render_settings(values: list[Setting]) -> str:
    return render_html(settings_page(values))


def write_settings(values: list[Setting], descriptor: int) -> int:
    return write_html_fd(settings_page(values), descriptor)


def main() -> str:
    return render_settings(settings())
