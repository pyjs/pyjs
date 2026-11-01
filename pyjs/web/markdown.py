"""Typed browser bindings for Markdown parsing and HTML sanitization."""

from collections.abc import Callable

from pyjs import js
from pyjs.tooling.npm import NpmImport, NpmPackage

__pyjs_npm_imports__ = (
    NpmImport(NpmPackage("markdown-it", "15.0.3"), "$markdown"),
    NpmImport(NpmPackage("dompurify", "3.4.17"), "$purify"),
)


@js.dictionary
class ParserOptions:
    def __init__(self, *, html: bool, linkify: bool, maxNesting: int):
        self.html = html
        self.linkify = linkify
        self.maxNesting = maxNesting


@js.dictionary
class SanitizeOptions:
    def __init__(self, *, ALLOWED_TAGS: list[str], ALLOWED_ATTR: list[str],
                 ALLOW_DATA_ATTR: bool, ALLOW_ARIA_ATTR: bool):
        self.ALLOWED_TAGS = ALLOWED_TAGS
        self.ALLOWED_ATTR = ALLOWED_ATTR
        self.ALLOW_DATA_ATTR = ALLOW_DATA_ATTR
        self.ALLOW_ARIA_ATTR = ALLOW_ARIA_ATTR


@js.native
class Token:
    def __init__(self):
        self.content = ""
        self.level = 0
        self.children: list[Token] | None = None


@js.native
class RendererRules:
    def __init__(self):
        self.image: Callable[[list[Token], int], str] | None = None
        self.text: Callable[[list[Token], int], str] | None = None


@js.native
class Renderer:
    def __init__(self):
        self.rules = RendererRules()


@js.native
class Parser:
    def __init__(self):
        self.renderer = Renderer()

    @js.inline("{self}.parse({text}, {{}})")
    def parse(self, text: str) -> list[Token]: ...

    @js.inline("{self}.renderer.render({tokens}, {self}.options, {{}})")
    def render_tokens(self, tokens: list[Token]) -> str: ...


@js.inline("new $markdown.default({options})")
def create_parser(options: ParserOptions) -> Parser: ...


@js.inline("$purify.default.sanitize({html}, {options})")
def sanitize(html: str, options: SanitizeOptions) -> str: ...


@js
def limit_tokens(parser: Parser, limit: int) -> None: ...


# Markdown-it chooses its state constructors at runtime. Intercept allocation
# there, before padded tables can amplify into a large token tree.
limit_tokens.source("""
let remaining = limit;
for (const stage of [parser.block, parser.inline]) {
    const State = stage.State;
    stage.State = class extends State {
        push(...args) {
            if (--remaining < 0) throw new Error('Markdown token limit');
            return super.push(...args);
        }
    };
}
""")
