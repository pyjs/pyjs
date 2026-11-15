"""Embed component styles consistently during SSR and browser construction."""

import re

from pyjs import js
from pyjs.web.domx import tag
from pyjs.web.ssr import raw_html


@js
def Stylesheet(css: str):
    """Embed trusted CSS; this does not sanitize untrusted stylesheets."""
    # Style is a raw-text HTML element: escaping `>` would break selectors.
    # Escape its closing delimiter so CSS string content cannot end the element.
    text = re.sub(r'</style', lambda match: r'\3c ' + match.group()[1:], css, flags=re.IGNORECASE)
    return tag('style', raw_html(text))


@Stylesheet.client
def Stylesheet(css: str):
    return tag('style', css)
