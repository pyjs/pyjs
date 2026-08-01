from pyjs import js
from pyjs.nativescript import Application, Button, EventData, Label, Page, StackLayout


@js
class Counter:
    def __init__(self):
        self.count = 0

        self.value = Label()
        self.value.id = "counter-value"
        self.value.testID = "counter-value"
        self.value.text = "0"
        self.value.className = "mb-6 text-center text-6xl font-bold text-slate-50"

        self.button = Button()
        self.button.id = "increment-button"
        self.button.testID = "increment-button"
        self.button.text = "Increment"
        self.button.className = "mx-8 h-14 rounded-lg bg-sky-400 text-xl font-semibold text-sky-950"
        self.button.on(Button.tapEvent, self.increment)

    def increment(self, event: EventData):
        self.count += 1
        self.value.text = str(self.count)

    def page(self) -> Page:
        content = StackLayout()
        content.className = "bg-slate-950 p-8"
        content.verticalAlignment = "middle"

        title = Label()
        title.text = "PyJS + NativeScript"
        title.className = "mb-4 text-center text-2xl font-bold text-sky-300"

        content.addChild(title)
        content.addChild(self.value)
        content.addChild(self.button)

        page = Page()
        page.actionBarHidden = True
        page.className = "bg-slate-950"
        page.content = content
        return page


@js
def create_page() -> Page:
    return Counter().page()


@js
def main():
    Application.run(create_page)
