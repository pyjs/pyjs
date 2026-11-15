"""Conversation layouts; applications supply messages, transport and actions."""

from typing import Final

from pyjs import JS, js
from pyjs.web.dom import Element, window
from pyjs.web.domx import button, div, ref, span, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget
from pyjs.web.ui.message_scroller import MessageScroller
from pyjs.web.ui.styles import Stylesheet

CHAT_CSS: Final[JS] = '''
[data-slot="chat-footer"] > :empty,
[data-slot="chat-footer"] > div:has(> button):not(:has(> button:not([hidden]))) {
  display: none;
}
[data-slot="chat-history"] [data-slot="message-content"] { gap: 6px; }
[data-slot="chat-history"] [data-slot="message-footer"] { padding-inline: 0; flex-wrap: wrap; }
[data-slot="chat-history"] { overflow-wrap: anywhere; }
[data-slot="chat-history"] [data-slot="message"] pre { overflow-wrap: normal; }
/* The automatic state must work before hydration knows the viewport width. */
[data-slot="chat-panel"][data-collapsed="auto"] [data-slot="chat-panel-open-label"] { display: none; }
@media (width < 1024px) {
  [data-slot="chat-panel"][data-collapsed="auto"] {
    height: auto; width: auto; border: 0; background: transparent; box-shadow: none;
  }
  [data-slot="chat-panel"][data-collapsed="auto"] [data-slot="chat-panel-header"] {
    border: 0; padding: 6px;
  }
  [data-slot="chat-panel"][data-collapsed="auto"] [data-slot="chat-panel-heading"],
  [data-slot="chat-panel"][data-collapsed="auto"] [data-slot="chat-panel-content"],
  [data-slot="chat-panel"][data-collapsed="auto"] [data-slot="chat-panel-close-label"] { display: none; }
  [data-slot="chat-panel"][data-collapsed="auto"] [data-slot="chat-panel-open-label"] { display: inline; }
  [data-slot="chat-history"] [data-slot="bubble"] { max-width: 92%; }
}
@media (width < 1024px) and (height < 450px) {
  [data-slot="chat-description"] { display: none; }
  [data-slot="chat-heading"] { padding-block: 0; }
}
'''


@js
def ChatView(*children, top_offset: str = '0px'):
    """A viewport-height conversation below an optional application header."""
    return div({'data-slot': 'chat-view', 'style': '--chat-top-offset:' + top_offset},
        tw('mx-auto flex h-[calc(100dvh-var(--chat-top-offset))] min-h-0 w-full max-w-5xl min-w-0 flex-1 flex-col px-2 lg:px-6'),
        Stylesheet(CHAT_CSS), *children)


@js
def ChatBody(*children):
    return div({'data-slot': 'chat-body'}, tw('flex h-full min-h-0 min-w-0 flex-1 flex-col'), *children)


@js
def ChatHeading(title: str, description: str = '', back_href: str = '', back_label: str = 'Back'):
    back = tag('a', {'href': back_href, 'aria-label': back_label},
               tw('flex size-11 shrink-0 items-center justify-center rounded-lg text-xl'), '←')
    if not back_href:
        back.setAttribute('hidden', '')
    return div({'data-slot': 'chat-heading'}, tw('flex min-w-0 shrink-0 items-center gap-2 py-2'),
        back,
        div(tw('min-w-0 flex-1'),
            tag('h1', {'title': title}, tw('line-clamp-1 text-base font-semibold break-words'), title),
            tag('p', {'data-slot': 'chat-description'}, tw('text-xs text-slate-500'), description)))


@js
def ChatNavigation(*children):
    return tag('nav', {'aria-label': 'Conversation sections'}, tw('flex shrink-0 gap-1 border-b pb-1 text-sm'), *children)


@js
def ChatLink(href: str, label: str, current: bool = False):
    return tag('a', {'href': href, 'aria-current': 'page' if current else 'false'},
        tw('inline-flex min-h-11 items-center rounded-md px-3 py-1.5 text-slate-500 hover:bg-slate-100 '
           'aria-[current=page]:bg-slate-100 aria-[current=page]:text-slate-950'), label)


@js
def ChatFooter(*children):
    return div({'data-slot': 'chat-footer'},
        tw('flex shrink-0 flex-col gap-2 border-t p-2 pb-[max(8px,env(safe-area-inset-bottom))]'),
        Stylesheet(CHAT_CSS), *children)


@js
class ChatHistory(MessageScroller):
    """MessageScroller with compact, unfaded conversation presentation."""
    def __init__(self, *children, label: str = 'Conversation', auto_scroll: bool = True):
        super().__init__(*children, label=label, auto_scroll=auto_scroll)
        self.setAttribute('data-slot', 'chat-history')
        self.viewport.removeAttribute('data-scroll-fade')
        self.viewport.style.setProperty('scrollbar-gutter', 'auto')
        self.viewport.style.setProperty('overflow-anchor', 'none')
        self.content.setAttribute('class', tw('flex h-max min-h-full flex-col gap-0 p-3 max-lg:px-1')['class'])
        self.add(Stylesheet(CHAT_CSS))


@js
class ChatPanel(Widget):
    """Persistent side conversation, full-width on mobile, with a compact toggle.

    Emits ``chat-panel-change`` after collapse/expansion. Application transport
    remains mounted while hidden. Mobile panels start collapsed, including before
    hydration; an explicit set_collapsed() choice takes precedence.
    """
    def __init__(self, heading: Element, content: Element, label: str = 'Assistant'):
        super().__init__()
        self.set_data('label', label)
        self.heading = ref(div({'data-slot': 'chat-panel-heading'}, tw('min-w-0 flex-1'), heading))
        self.content = ref(div({'data-slot': 'chat-panel-content'}, tw('flex min-h-0 flex-1 flex-col'), content))
        self.toggle = ref(button({'type': 'button', 'data-slot': 'chat-panel-toggle', 'aria-label': 'Toggle ' + label},
            tw('min-h-11 rounded-lg border bg-[var(--pyjs-surface,white)] px-3 py-2 text-sm'),
            span({'data-slot': 'chat-panel-open-label'}, label),
            span({'data-slot': 'chat-panel-close-label'}, 'Close')))
        self.add(tw('group/chat-panel sticky top-0 z-40 flex h-dvh w-[360px] min-w-0 max-w-full shrink-0 flex-col '
                    'border-l bg-[var(--pyjs-surface,white)] max-lg:fixed max-lg:right-0 max-lg:w-full '
                    'max-lg:border-l-0 max-lg:shadow-xl data-[collapsed=true]:h-auto data-[collapsed=true]:w-auto '
                    'data-[collapsed=true]:border-0 data-[collapsed=true]:bg-transparent data-[collapsed=true]:shadow-none'),
            {'data-slot': 'chat-panel', 'data-collapsed': 'auto'}, Stylesheet(CHAT_CSS),
            div({'data-slot': 'chat-panel-header'}, tw('flex shrink-0 items-center justify-between gap-2 border-b p-3 '
                   'group-data-[collapsed=true]/chat-panel:border-0 group-data-[collapsed=true]/chat-panel:p-1.5'),
                self.heading, self.toggle), self.content)

    def initialize(self):
        self.toggle.addEventListener('click', self.toggle_panel)
        state = self.getAttribute('data-collapsed')
        self.set_collapsed(window.innerWidth < 1024 if state == 'auto' else state == 'true')

    def toggle_panel(self, event: Event):
        self.set_collapsed(self.getAttribute('data-collapsed') != 'true')

    def set_collapsed(self, hidden: bool):
        changed = (self.getAttribute('data-collapsed') == 'true') != hidden
        self.setAttribute('data-collapsed', 'true' if hidden else 'false')
        self.content.hidden = hidden
        self.heading.hidden = hidden
        self.toggle.textContent = (self.get_data('label') or 'Assistant') if hidden else 'Close'
        self.toggle.setAttribute('aria-label', ('Open ' if hidden else 'Close ') + (self.get_data('label') or 'Assistant'))
        self.toggle.setAttribute('aria-expanded', 'false' if hidden else 'true')
        if changed:
            self.dispatchEvent(Event('chat-panel-change'))
