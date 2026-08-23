import pytest
from pyjs.web.ssr import render_html
from pyjs_extras.stripe.simulator_ui import status_badge


@pytest.mark.parametrize("status", ["canceled", "failed", "unpaid", "uncollectible"])
def test_terminal_status_badges_are_visually_distinct(status: str):
    assert render_html(status_badge(status)) == (
        '<span class="inline-flex rounded-full bg-red-100 px-2.5 py-1 text-xs '
        f'font-semibold text-red-800">{status}</span>'
    )
