from pyjs import js
from pyjs.dom import Event
from pyjs.domx import CustomElement, tag, tw


@js
class CounterApp(CustomElement):

    def __init__(self):
        super().__init__()
        self.counter_text = tag("div", tw("text-4xl font-mono text-blue-600"), "0")
        self.sub_button = tag("button", tw("px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg"), "-")
        self.sub_button.addEventListener("click", self.decrement)
        self.add_button = tag("button", tw("px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg"), "+")
        self.add_button.addEventListener("click", self.increment)
        tag(self,
            tag("body", tw("bg-gray-100 flex items-center justify-center h-screen"),
                tag("div", tw("bg-white shadow-md rounded-xl p-6 w-80 text-center space-y-6"),
                    tag("h1", tw("text-2xl font-bold"), "Counter"),
                    self.counter_text,
                    tag("div", tw("flex justify-center space-x-4"),
                        self.sub_button,
                        self.add_button,
                    ),
                ),
            )
        )

    def get_counter(self):
        return int(self.counter_text.textContent.strip())

    def decrement(self, e: Event):
        self.counter_text.textContent = str(self.get_counter() - 1)

    def increment(self, e: Event):
        self.counter_text.textContent = str(self.get_counter() + 1)


def main():
    return CounterApp()


if __name__ == "__main__":
    from pathlib import Path
    from pyjs.server import serve
    serve(Path(__file__).stem)
