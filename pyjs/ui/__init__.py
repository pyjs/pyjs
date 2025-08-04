from pyjs.domx import CustomElement, tag


class Widget(CustomElement):

    def add(self, *children):
        tag(self, *children)
