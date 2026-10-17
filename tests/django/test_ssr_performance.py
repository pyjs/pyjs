import gc
import statistics
import time
from dataclasses import dataclass

from django.template import Context, Engine

from pyjs.web.domx import CustomElement, div, p, span, tag, tw
from pyjs.web.ssr import render_html


@dataclass(frozen=True)
class _Setting:
    custom_id: str
    name: str
    description: str
    risk: str
    changed: bool
    changed_text: str
    restart: bool
    restart_text: str
    search: str
    values: tuple[tuple[str, str], ...]
    guidance: str
    extra: str


_SETTINGS = tuple(
    _Setting(
        custom_id=f"ce{index + 1}",
        name=f"work_mem_{index}",
        description="Memory available to query operations & sorts.",
        risk=(
            "high"
            if index % 11 == 0
            else "caution"
            if index % 7 == 0
            else "routine"
        ),
        changed=index % 5 == 0,
        changed_text="true" if index % 5 == 0 else "false",
        restart=index % 7 == 0,
        restart_text="true" if index % 7 == 0 else "false",
        search=f"work_mem_{index} resource usage memory",
        values=(
            ("Current", "4096 kB"),
            ("Default", "4096"),
            ("Reset", "4096"),
            ("Source", "default"),
            ("Type", "integer"),
            ("Range", "64 – 2147483647"),
        ),
        guidance="Estimate peak concurrent sorts and hashes.",
        extra=(
            "Review workload concurrency before increasing this value."
            if index % 3 == 0
            else ""
        ),
    )
    for index in range(48)
)


_DJANGO_TEMPLATE = "".join(
    (
        '<div class="catalog rounded" data-settings="">',
        "{% for setting in settings %}",
        '<details class="setting border-b" ',
        'data-setting="{{ setting.search }}" ',
        'data-risk="{{ setting.risk }}" ',
        'data-changed="{{ setting.changed_text }}" ',
        'data-restart="{{ setting.restart_text }}">',
        '<summary class="summary px-4 py-3">',
        '<div class="heading flex"><div>',
        '<code class="name font-semibold">{{ setting.name }}</code>',
        '<p class="description text-xs">{{ setting.description }}</p>',
        '</div><div class="badges flex">',
        '<span class="badge px-2 text-xs" data-variant="outline">',
        "{{ setting.risk }}</span>",
        "{% if setting.changed %}",
        '<span class="badge px-2 text-xs" data-variant="secondary">',
        "non-default</span>{% endif %}",
        "{% if setting.restart %}",
        '<span class="badge px-2 text-xs" data-variant="default">',
        "restart pending</span>{% endif %}",
        "</div></div></summary>",
        '<div class="body grid"><div class="values grid">',
        "{% for label, value in setting.values %}<div>",
        '<p class="label text-xs">{{ label }}</p>',
        '<p class="value text-sm">{{ value }}</p>',
        "</div>{% endfor %}</div>",
        '<benchmark-setting data-self-id="{{ setting.custom_id }}" ',
        'class="custom setting-guidance">',
        '<p class="guidance text-sm">{{ setting.guidance }}</p>',
        "{% if setting.extra %}",
        '<p class="extra text-xs">{{ setting.extra }}</p>',
        "{% else %}<span></span>{% endif %}",
        "</benchmark-setting></div></details>{% endfor %}</div>",
    )
)


def _badge(text, variant):
    return span(
        tw("badge px-2 text-xs"),
        {"data-variant": variant},
        text,
    )


class BenchmarkSetting(CustomElement):
    def __init__(self, setting):
        super().__init__()
        tag(
            self,
            tw("custom setting-guidance"),
            p(tw("guidance text-sm"), setting.guidance),
            p(tw("extra text-xs"), setting.extra)
            if setting.extra
            else span(),
        )


def _setting_row(setting):
    badges = [_badge(setting.risk, "outline")]
    if setting.changed:
        badges.append(_badge("non-default", "secondary"))
    if setting.restart:
        badges.append(_badge("restart pending", "default"))
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
            div(
                tw("values grid"),
                *[
                    div(
                        p(tw("label text-xs"), label),
                        p(tw("value text-sm"), value),
                    )
                    for label, value in setting.values
                ],
            ),
            BenchmarkSetting(setting),
        ),
    )


def _render_pyjs_settings():
    counter = CustomElement.CUSTOM_ELEMENT_COUNTER
    CustomElement.CUSTOM_ELEMENT_COUNTER = 0
    try:
        return render_html(
            div(
                tw("catalog rounded"),
                {"data-settings": ""},
                *[_setting_row(setting) for setting in _SETTINGS],
            )
        )
    finally:
        CustomElement.CUSTOM_ELEMENT_COUNTER = counter


def _measure_batch(function, loops):
    started = time.perf_counter_ns()
    for _ in range(loops):
        function()
    return (time.perf_counter_ns() - started) / loops


def test_pyjs_ssr_is_faster_than_compiled_django_template():
    """Protect end-to-end construction and serialization performance."""
    template = Engine(autoescape=True).from_string(_DJANGO_TEMPLATE)
    context = Context({"settings": _SETTINGS}, autoescape=True)

    def render_django_settings():
        return template.render(context)

    assert _render_pyjs_settings() == render_django_settings()

    for _ in range(5):
        _render_pyjs_settings()
        render_django_settings()

    gc_was_enabled = gc.isenabled()
    gc.enable()
    try:
        ratios = []
        for sample in range(25):
            functions = (
                (_render_pyjs_settings, render_django_settings)
                if sample % 2 == 0
                else (render_django_settings, _render_pyjs_settings)
            )
            elapsed = {
                function: _measure_batch(function, loops=10)
                for function in functions
            }
            ratios.append(
                elapsed[_render_pyjs_settings] / elapsed[render_django_settings]
            )
    finally:
        if not gc_was_enabled:
            gc.disable()

    median_ratio = statistics.median(ratios)
    assert median_ratio < 1.0, (
        "PyJS SSR must remain faster than the equivalent compiled "
        f"Django template; measured ratio: {median_ratio:.3f}"
    )
