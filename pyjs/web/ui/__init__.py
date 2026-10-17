"""Web components organized as focused, tree-shakeable modules.

Import controls from modules such as ``pyjs.web.ui.button`` and
``pyjs.web.ui.dialog`` rather than from this package root. Run
``pyjs template pyjs_examples.components`` for the installed component catalog.
The package root intentionally avoids re-exporting every component because that
would make the supported import and tree-shaking boundary less obvious.
"""

from pyjs.web.crypto import crypto
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ProxyElement, tag

__all__ = ["Widget"]


class Widget(CustomElement):
    """Base custom element for reusable PyJS web controls."""
    def add(self, *children: str | dict[str, str] | Element | ProxyElement):
        tag(self, *children)

    def get_component_id(self) -> str:
        server_id = self.get_data("self-id")
        if server_id is not None:
            return server_id
        client_id = self.get_data("component-id")
        if client_id is not None:
            return client_id
        generated_id = "ui-" + crypto.randomUUID()
        self.set_data("component-id", generated_id)
        return generated_id
