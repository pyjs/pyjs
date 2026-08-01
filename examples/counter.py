"""A compact reactive counter demonstrating state, effects, and DOM event handling."""

from pyjs import effect, js, state
from pyjs.web.domx import CustomElement, ref, tag, tw
from pyjs.web.events import Event


@js
class CounterApp(CustomElement):
    count = state(0)

    def __init__(self):
        super().__init__()
        self.counter_text = ref(tag("div", tw("text-4xl font-mono text-blue-600")))
        self.sub_button = tag(
            "button", tw("px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg"), "-"
        )
        self.sub_button.addEventListener("click", self.decrement)
        self.add_button = tag(
            "button", tw("px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg"), "+"
        )
        self.add_button.addEventListener("click", self.increment)
        tag(
            self,
            tag(
                "body",
                tw("bg-gray-100 flex items-center justify-center h-screen"),
                tag(
                    "div",
                    tw("bg-white shadow-md rounded-xl p-6 w-80 text-center space-y-6"),
                    tag("h1", tw("text-2xl font-bold"), "Counter"),
                    self.counter_text,
                    tag(
                        "div",
                        tw("flex justify-center space-x-4"),
                        self.sub_button,
                        self.add_button,
                    ),
                ),
            ),
        )

    @effect(count)
    def render_count(self):
        self.counter_text.textContent = str(self.count)

    def decrement(self, e: Event):
        self.count -= 1

    def increment(self, e: Event):
        self.count += 1


def main():
    return CounterApp()


@js
def test_counter_updates_its_state():
    app = CounterApp()

    app.increment(Event("click"))
    app.increment(Event("click"))
    app.decrement(Event("click"))

    assert app.count == 1
    assert app.counter_text.textContent == "1"


if __name__ == "__main__":
    from pyjs.server import serve

    serve(__file__)
