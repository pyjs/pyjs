from pyjs.web.crypto import crypto
from pyjs.web.domx import CustomElement, tag


class Widget(CustomElement):
    def add(self, *children):
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
