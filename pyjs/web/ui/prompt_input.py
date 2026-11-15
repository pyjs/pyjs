from typing import Final

from pyjs import JS, js
from pyjs.web.dom import Document, DocumentFragment, Element
from pyjs.web.domx import div, ref, require_element, tw
from pyjs.web.events import KeyboardEvent
from pyjs.web.html import (
    HTMLButtonElement,
    HTMLFormElement,
    HTMLInputElement,
    HTMLTextAreaElement,
)
from pyjs.web.ui import Widget
from pyjs.web.ui.input_group import InputGroup, InputGroupAddon
from pyjs.web.ui.styles import Stylesheet

PROMPT_CSS: Final[JS] = '''
[data-slot="prompt-input"][data-layout="compact"] > [data-slot="input-group"] {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end;
  border-radius: 1rem;
}
[data-slot="prompt-input"] [data-slot="prompt-attachments"] {
  grid-column: 1 / -1; padding: 6px; min-width: 0;
}
[data-slot="prompt-input"][data-layout="compact"] [data-slot="input-group-addon"] {
  width: auto; height: auto; padding: 4px 6px 4px 0;
}
[data-slot="prompt-input"][data-layout="compact"] [data-slot="input-group-control"] {
  display: block; width: 100%; field-sizing: content; resize: none;
  min-height: 44px; max-height: min(128px, 25dvh);
  font-size: 16px; line-height: 24px;
}
[data-slot="prompt-input"][data-layout="compact"] button {
  min-height: 44px; min-width: 44px;
}
/* Leave the transcript in place when the IME leaves too little room for
   the page heading, attachments and editor together. Focus transfers to
   actions keep this positioning until their activation has finished. */
@media (width < 1024px) and (height < 450px) {
  [data-slot="prompt-input"][data-layout="compact"]:focus-within {
    position: fixed; inset: auto 0 0; z-index: 60; margin: 0;
    background: var(--pyjs-surface, white);
  }
}
/* A landscape IME can leave only a few text lines visible. Preserve the
   editing surface and its actions throughout focus transfers between them. */
@media (width < 1024px) and (height < 240px) {
  [data-slot="prompt-input"][data-layout="compact"]:focus-within {
    position: fixed; inset: 0; z-index: 60; margin: 0;
    background: var(--pyjs-surface, white);
  }
  [data-slot="prompt-input"][data-layout="compact"]:focus-within > [data-slot="input-group"] {
    height: 100%; min-height: 0; border: 0; border-radius: 0;
    grid-template-rows: minmax(0, 1fr); align-items: center;
  }
  [data-slot="prompt-input"][data-layout="compact"]:focus-within [data-slot="prompt-control"] {
    height: 100%; min-height: 0; overflow: hidden;
  }
  [data-slot="prompt-input"][data-layout="compact"]:focus-within textarea {
    height: 100%; min-height: 0; max-height: none; padding-block: 4px;
    field-sizing: fixed;
  }
  [data-slot="prompt-input"][data-layout="compact"]:focus-within [data-slot="prompt-attachments"] {
    display: none;
  }
  [data-slot="prompt-input"][data-layout="compact"]:focus-within button {
    min-height: 0; height: min(44px, calc(100dvh - 8px));
  }
}
'''


@js
def prompt_attachments():
    slot = InputGroupAddon(align='block-start')
    slot.setAttribute('data-slot', 'prompt-attachments')
    slot.setAttribute('hidden', '')
    return slot


@js
class PromptInput(Widget):
    """Form composer with public action/attachment slots and IME-safe editing.

    ``compact`` places actions beside the text and preserves usable controls
    in short mobile viewports. Enter submits; Shift+Enter and IME edit text.
    """

    def __init__(self, control: Element, *actions, compact: bool = False):
        super().__init__()
        self.actions = ref(InputGroupAddon(*actions, align="block-end"))
        self.attachments = ref(prompt_attachments())
        self.add(tw("block min-w-0"),
            {"data-slot": "prompt-input", 'data-layout': 'compact' if compact else 'stacked'},
            Stylesheet(PROMPT_CSS), InputGroup(
                div({'data-slot': 'prompt-control'}, tw("min-w-0 w-full p-1"), control),
                self.actions, self.attachments))

    @js
    def set_attachments(self, content: Element):
        self.attachments.replaceChildren(content)

    @set_attachments.client
    def set_attachments(self, content: Element):
        # Parents can supply upload controls before this SSR child initializes.
        require_element(self, '[data-slot=prompt-attachments]').replaceChildren(content)

    @js
    def show_attachments(self, visible: bool):
        self.attachments.hidden = not visible

    @show_attachments.client
    def show_attachments(self, visible: bool):
        require_element(self, '[data-slot=prompt-attachments]').toggleAttribute('hidden', not visible)

    @js
    def append_action(self, action: Element):
        self.actions.append(action)

    @append_action.client
    def append_action(self, action: Element):
        require_element(self, '[data-slot=input-group-addon][data-align=block-end]').appendChild(action)

    @js
    def prepend_action(self, action: Element):
        self.actions.replaceChildren(action, *self.actions.childNodes)

    @prepend_action.client
    def prepend_action(self, action: Element):
        require_element(self, '[data-slot=input-group-addon][data-align=block-end]').prepend(action)

    def initialize(self):
        self.addEventListener("keydown", self.keydown)

    def keydown(self, event: KeyboardEvent):
        if (event.defaultPrevented or event.key != "Enter" or event.shiftKey or event.isComposing
                or event.keyCode == 229
                or not isinstance(event.target, HTMLTextAreaElement)):
            return
        form = event.target.form
        if isinstance(form, HTMLFormElement):
            event.preventDefault()
            if event.repeat:
                return
            root = form.getRootNode()
            # Form ownership may cross the descendant tree. form.elements also
            # excludes image submitters, so inspect controls in tree order.
            if isinstance(root, (Document, DocumentFragment, Element)):
                for submitter in root.querySelectorAll('button,input'):
                    if (isinstance(submitter, (HTMLButtonElement, HTMLInputElement))
                            and submitter.form is form and submitter.type in ('submit', 'image')):
                        if not submitter.matches(':disabled'):
                            form.requestSubmit(submitter)
                        return
            form.requestSubmit()
