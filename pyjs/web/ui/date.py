from datetime import date

from pyjs import js
from pyjs.javascript import Date
from pyjs.web.dom import Element
from pyjs.web.domx import tag


@js
def format_date(value: date) -> str:
    return value.strftime("%x")


@format_date.client
@js.inline(
    "(typeof {value} === 'string' ? new Date({value} + 'T00:00:00') : "
    "{value}).toLocaleDateString()"
)
def format_date(value: Date | str) -> str:
    if isinstance(value, str):
        return Date(value + "T00:00:00").toLocaleDateString()
    return value.toLocaleDateString()


@js
def iso_date(value: date) -> str:
    return value.isoformat()


@iso_date.client
@js.inline(
    "(typeof {value} === 'string' ? {value} : "
    "String({value}.getFullYear()) + '-' + "
    "String({value}.getMonth() + 1).padStart(2, '0') + '-' + "
    "String({value}.getDate()).padStart(2, '0'))"
)
def iso_date(value: Date | str) -> str:
    if isinstance(value, str):
        return value
    month = str(value.getMonth() + 1)
    day = str(value.getDate())
    if len(month) == 1:
        month = "0" + month
    if len(day) == 1:
        day = "0" + day
    return str(value.getFullYear()) + "-" + month + "-" + day


@js
def DateText(value: date) -> Element:
    return tag(
        "time",
        {"datetime": iso_date(value)},
        format_date(value),
    )
