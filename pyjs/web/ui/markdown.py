"""Browser Markdown for untrusted, incrementally updated conversation text."""

from pyjs import js
from pyjs.tooling.npm import NpmImport, NpmPackage
from pyjs.web.dom import Element
from pyjs.web.domx import ref, tag, tw
from pyjs.web.ui import Widget
from pyjs.web.ui.typeset import Typeset

__pyjs_npm_imports__ = (
    NpmImport(NpmPackage("markdown-it", "15.0.3"), "$markdown"),
    NpmImport(NpmPackage("dompurify", "3.4.17"), "$purify"),
)


@js.inline(r"""((element, text) => {{
    try {{
        const parser = new $markdown.default({{html: false, linkify: true, maxNesting: 20}});
        // A short table can expand into many padded cells. Stop token creation
        // before amplification reaches the sanitizer or browser layout.
        const tokenLimit = 8192;
        let remaining = tokenLimit;
        for (const stage of [parser.block, parser.inline]) {{
            const State = stage.State;
            stage.State = class extends State {{
                push(...args) {{
                    if (--remaining < 0) throw new Error('Markdown token limit');
                    return super.push(...args);
                }}
            }};
        }}
        parser.renderer.rules.image = (tokens, index) => parser.utils.escapeHtml(tokens[index].content);
        const tokens = parser.parse(text, {{}});
        // The parser discards blocks beyond its nesting limit. Preserve the
        // entire source as text instead of silently losing that content.
        let size = 0;
        for (const token of tokens) {{
            size += 1 + (token.children?.length || 0);
            if (token.level >= 19 || size > tokenLimit) throw new Error('Markdown complexity limit');
        }}
        element.innerHTML = $purify.default.sanitize(parser.renderer.render(tokens, parser.options, {{}}), {{
            ALLOWED_TAGS: ['p','br','strong','em','del','s','code','pre','blockquote','ul','ol','li',
                'h1','h2','h3','h4','h5','h6','hr','a','table','thead','tbody','tr','th','td'],
            ALLOWED_ATTR: ['href','title','start'], ALLOW_DATA_ATTR: false, ALLOW_ARIA_ATTR: false
        }});
        for (const link of element.querySelectorAll('a')) {{
            const href = link.getAttribute('href') || '';
            if (!/^https?:\/\//i.test(href)) link.removeAttribute('href');
            else {{ link.setAttribute('target', '_blank'); link.setAttribute('rel', 'noopener noreferrer'); }}
        }}
        element.className = '';
    }} catch {{
        element.textContent = text;
        element.className = 'whitespace-pre-wrap';
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
        source = self.get_data('source')
        self.set_text(source if source is not None else self.body.textContent or "")

    def set_text(self, text: str):
        self.set_data('source', text)
        render_markdown(self.body, text)
