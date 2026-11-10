"""Browser Markdown for untrusted, incrementally updated conversation text."""

from collections.abc import Callable

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
def render_markdown(
    element: Element, text: str, resolve_link: Callable[[str], str] | None = None,
    on_image: Callable[[str], None] | None = None
) -> None:
    # Only the browser sanitizer may introduce markup; SSR remains escaped text.
    element.textContent = text


@js
def _render_html(parser: Parser, text: str, images: list[str]) -> str:
    token_limit = 8192
    limit_tokens(parser, token_limit)
    # The existing text rule escapes the label without creating an image.
    parser.renderer.rules.image = parser.renderer.rules.text
    tokens = parser.parse(text)
    # The parser can discard over-nested blocks, but not inline emphasis.
    # Check only block-level tokens before traversing their inline children.
    if any(token.level >= 19 for token in tokens):
        raise ValueError("Markdown complexity limit")
    # Include nested image descriptions in the same traversal and budget.
    pending = list(reversed(tokens))
    size = 0
    while pending:
        token = pending.pop()
        size += 1
        if size > token_limit:
            raise ValueError("Markdown complexity limit")
        if token.type == 'image':
            source = token.attrGet('src')
            if source is not None:
                images.append(source)
        if token.children is not None:
            pending.extend(reversed(token.children))
    return sanitize(parser.render_tokens(tokens), SanitizeOptions(
        ALLOWED_TAGS=['p', 'br', 'strong', 'em', 'del', 's', 'code', 'pre',
                      'blockquote', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4',
                      'h5', 'h6', 'hr', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
        ALLOWED_ATTR=['href', 'title', 'start'],
        ALLOW_DATA_ATTR=False, ALLOW_ARIA_ATTR=False,
    ))


@render_markdown.client
def render_markdown(
    element: Element, text: str, resolve_link: Callable[[str], str] | None = None,
    on_image: Callable[[str], None] | None = None
) -> None:
    images: list[str] = []
    try:
        parser = create_parser(ParserOptions(html=False, linkify=True, maxNesting=20))
        element.innerHTML = _render_html(parser, text, images)
        for link in element.querySelectorAll('a'):
            original = link.getAttribute('href') or ''
            href = resolve_link(original) if resolve_link is not None else original
            external = href.lower().startswith(('https://', 'http://'))
            local = resolve_link is not None and href.startswith('/') and not href.startswith('//')
            if not (external or local) or '\\' in href or any(ord(c) < 32 for c in href):
                link.removeAttribute('href')
            else:
                link.setAttribute('href', href)
                if external:
                    link.setAttribute('target', '_blank')
                    link.setAttribute('rel', 'noopener noreferrer')
        element.className = ''
        if on_image is not None:
            for source in images:
                on_image(source)
    except Exception:
        element.textContent = text
        element.className = 'whitespace-pre-wrap'


@js
class Markdown(Widget):
    """Sanitized Markdown; raw media and styles are disabled.

    Override resolve_link to map source links to application routes.
    Inputs use parser-normalized, percent-encoded URLs. Returned URLs must use
    HTTP(S) or an absolute local path; other schemes are refused.
    """

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
        render_markdown(self.body, text, self.resolve_link, self.image_reference)

    def resolve_link(self, href: str) -> str:
        """Allow external HTTP(S) links by default, without loading any media."""
        return href if href.lower().startswith(('https://', 'http://')) else ''

    def image_reference(self, source: str) -> None:
        """Observe an image reference without rendering or fetching it.

        Applications can override this to build a separately authorized gallery.
        Each successful browser render reports all references again, including
        nested descriptions. Sources are untrusted, parser-normalized URLs with
        percent encoding; the default widget never loads images.
        """
        pass
