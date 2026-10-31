"""Browser Markdown for untrusted, incrementally updated conversation text."""

from pyjs import js
from pyjs.tooling.npm import NpmImport, NpmPackage
from pyjs.web.dom import Element
from pyjs.web.domx import ref, tag, tw
from pyjs.web.ui import Widget
from pyjs.web.ui.typeset import Typeset

__pyjs_npm_imports__ = (
    NpmImport(NpmPackage("marked", "18.1.2"), "$marked"),
    NpmImport(NpmPackage("dompurify", "3.4.17"), "$purify"),
)


@js.inline(r"""((element, text) => {{
    element.innerHTML = $purify.default.sanitize($marked.marked.parse(text, {{async: false}}), {{
        ALLOWED_TAGS: ['p','br','strong','em','del','code','pre','blockquote','ul','ol','li',
            'h1','h2','h3','h4','h5','h6','hr','a','table','thead','tbody','tr','th','td'],
        ALLOWED_ATTR: ['href','title','start'], ALLOW_DATA_ATTR: false, ALLOW_ARIA_ATTR: false
    }});
    for (const link of element.querySelectorAll('a')) {{
        const href = link.getAttribute('href') || '';
        if (!/^https?:\/\//i.test(href)) link.removeAttribute('href');
        else {{ link.setAttribute('target', '_blank'); link.setAttribute('rel', 'noopener noreferrer'); }}
    }}
}})({element}, {text})""")
def render_markdown(element: Element, text: str) -> None:
    # Server rendering stays escaped text. Only the browser sanitizer may
    # introduce markup; images and other automatic network requests are absent.
    element.textContent = text


@js
class Markdown(Widget):
    """Sanitized Markdown; raw media, styles, and application-relative links are disabled."""

    def __init__(self, text: str):
        super().__init__()
        self.add(tw("block min-w-0 overflow-x-auto"), {"data-slot": "markdown"})
        self.body = ref(tag("div", tw("whitespace-pre-wrap"), text))
        self.append(Typeset(self.body, preset="chat"))

    def initialize(self):
        self.set_text(self.body.textContent or "")

    def set_text(self, text: str):
        render_markdown(self.body, text)
        self.body.setAttribute("class", "")
