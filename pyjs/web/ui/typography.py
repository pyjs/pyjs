from pyjs import js
from pyjs.web.domx import a, p, tag, tw


@js
def TypographyH1(*children):
    return tag("h1", tw("scroll-m-20 text-4xl font-extrabold tracking-tight"), *children)


@js
def TypographyH2(*children):
    return tag(
        "h2",
        tw(
            "scroll-m-20 border-b border-slate-200 pb-2 text-3xl font-semibold tracking-tight"
        ),
        *children,
    )


@js
def TypographyH3(*children):
    return tag("h3", tw("scroll-m-20 text-2xl font-semibold tracking-tight"), *children)


@js
def TypographyH4(*children):
    return tag("h4", tw("scroll-m-20 text-xl font-semibold tracking-tight"), *children)


@js
def TypographyP(*children):
    return p(tw("leading-7 [&:not(:first-child)]:mt-6"), *children)


@js
def TypographyBlockquote(*children):
    return tag(
        "blockquote", tw("mt-6 border-l-2 border-slate-300 pl-6 italic"), *children
    )


@js
def TypographyList(*children):
    return tag("ul", tw("my-6 ml-6 list-disc [&>li]:mt-2"), *children)


@js
def TypographyInlineCode(*children):
    return tag(
        "code",
        tw("rounded bg-slate-100 px-1.5 py-1 font-mono text-sm font-semibold"),
        *children,
    )


@js
def TypographyLead(*children):
    return p(tw("text-xl text-slate-500"), *children)


@js
def TypographyLarge(*children):
    return tag("div", tw("text-lg font-semibold"), *children)


@js
def TypographySmall(*children):
    return tag("small", tw("text-sm font-medium leading-none"), *children)


@js
def TypographyMuted(*children):
    return p(tw("text-sm text-slate-500"), *children)


@js
def TypographyLink(href: str, *children):
    return a(tw("font-medium underline underline-offset-4"), {"href": href}, *children)
