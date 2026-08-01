from pyjs import effect, js, state
from pyjs.web.domx import CustomElement, button, ref, tag
from pyjs.web.events import Event


@js
class Counter(CustomElement):
    count = state(0)

    def __init__(self):
        super().__init__()
        self.value = ref(tag("strong", {"style": "font-size:3rem"}, "0"))
        self.decrement_button = ref(button({"type": "button"}, "−"))
        self.increment_button = ref(button({"type": "button"}, "+"))
        self.decrement_button.addEventListener("click", self.decrement)
        self.increment_button.addEventListener("click", self.increment)
        tag(
            self,
            tag(
                "main",
                {
                    "style": (
                        "min-height:100vh;display:grid;place-items:center;background:#f8fafc;"
                        "font:16px system-ui,sans-serif"
                    )
                },
                tag(
                    "section",
                    {
                        "style": (
                            "display:grid;grid-template-columns:3rem 8rem 3rem;align-items:center;"
                            "gap:1rem;text-align:center"
                        )
                    },
                    self.decrement_button,
                    self.value,
                    self.increment_button,
                ),
            ),
        )

    @effect(count)
    def render_count(self):
        self.value.textContent = str(self.count)

    def decrement(self, event: Event):
        self.count -= 1

    def increment(self, event: Event):
        self.count += 1


def main():
    return Counter()


if __name__ == "__main__":
    from pyjs.server import serve

    serve("state_counter")
