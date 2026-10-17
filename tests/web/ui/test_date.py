from datetime import date

import pytest

from pyjs import js
from pyjs.javascript import Date
from pyjs.web.ssr import render_html
from pyjs.web.ui.date import DateText


def test_date_text_serializes_the_date_and_formats_it_for_ssr():
    value = date(2026, 8, 30)

    assert render_html(DateText(value)) == (
        '<time datetime="2026-08-30">' + value.strftime("%x") + "</time>"
    )


@pytest.mark.pyjs_web
@js
def test_date_text_formats_an_iso_date_in_the_browser():
    value: date = Date("2026-08-30T00:00:00")
    element = DateText(value)

    assert element.getAttribute("datetime") == "2026-08-30"
    assert element.textContent != "2026-08-30"
