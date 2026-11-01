"""Browser Markdown for untrusted, incrementally updated conversation text."""

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import ref, tag, tw
from pyjs.web.markdown import (
    Parser,
    ParserOptions,
    SanitizeOptions,
    create_parser,
    limit_tokens,
    sanitize,
)
from pyjs.web.markdown import (
    __pyjs_npm_imports__ as __pyjs_npm_imports__,
)
from pyjs.web.ui import Widget
from pyjs.web.ui.typeset import Typeset


@js
def render_markdown(element: Element, text: str) -> None:
    # Only the browser sanitizer may introduce markup; SSR remains escaped text.
    element.textContent = text


@js
def _render_html(parser: Parser, text: str) -> str:
    token_limit = 8192
    limit_tokens(parser, token_limit)
    # The existing text rule escapes the label without creating an image.
    parser.renderer.rules.image = parser.renderer.rules.text
    tokens = parser.parse(text)
    # The parser discards blocks beyond its nesting limit. Preserve the
    # entire source as text instead of silently losing that content.
    size = 0
    for token in tokens:
        children = token.children
        size += 1 + (len(children) if children is not None else 0)
        if token.level >= 19 or size > token_limit:
            raise ValueError("Markdown complexity limit")
    return sanitize(parser.render_tokens(tokens), SanitizeOptions(
        ALLOWED_TAGS=['p', 'br', 'strong', 'em', 'del', 's', 'code', 'pre',
                      'blockquote', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4',
                      'h5', 'h6', 'hr', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
        ALLOWED_ATTR=['href', 'title', 'start'],
        ALLOW_DATA_ATTR=False, ALLOW_ARIA_ATTR=False,
    ))


@render_markdown.client
def render_markdown(element: Element, text: str) -> None:
    try:
        parser = create_parser(ParserOptions(html=False, linkify=True, maxNesting=20))
        element.innerHTML = _render_html(parser, text)
        for link in element.querySelectorAll('a'):
            href = (link.getAttribute('href') or '').lower()
            if not href.startswith('https://') and not href.startswith('http://'):
                link.removeAttribute('href')
            else:
                link.setAttribute('target', '_blank')
                link.setAttribute('rel', 'noopener noreferrer')
        element.className = ''
    except Exception:
        element.textContent = text
        element.className = 'whitespace-pre-wrap'


@js
class Markdown(Widget):
    """Sanitized Markdown; raw media, styles, and application-relative links are disabled."""

    def __init__(self, text: str):
        super().__init__()
        self.add(tw("block min-w-0 overflow-x-auto"), {"data-slot": "markdown"})
        self.body = ref(tag("div", tw("whitespace-pre-wrap"), text))
        self.append(Typeset(self.body, preset="chat"))

    def initialize(self):
        source = self.get_data('source')
        self.set_text(source if source is not None else self.body.textContent or "")

    def set_text(self, text: str):
        self.set_data('source', text)
        render_markdown(self.body, text)
