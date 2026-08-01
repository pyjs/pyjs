from pyjs import js, js_object, js_str


@js(builtin=True)
class EventData:
    def __init__(self):
        self.eventName = ""
        self.object = View()


@js(builtin=True)
class View:
    def __init__(self):
        self.id = ""
        self.testID = ""
        self.className = ""
        self.backgroundColor = ""
        self.color = ""
        self.height: int | str = "auto"
        self.width: int | str = "auto"
        self.horizontalAlignment = "stretch"
        self.verticalAlignment = "stretch"
        self.margin: int | str = 0
        self.padding: int | str = 0

    def on(self, event_name: str, callback: callable): ...


@js(builtin=True)
class StackLayout(View):
    def __init__(self):
        super().__init__()
        self.orientation = "vertical"
        self.children: list[View] = []

    def addChild(self, child: View):
        self.children.append(child)


@js(builtin=True)
class Page(View):
    def __init__(self):
        super().__init__()
        self.actionBarHidden = False
        self.content = View()


@js(builtin=True)
class Label(View):
    def __init__(self):
        super().__init__()
        self.text = ""
        self.fontSize = 14
        self.fontWeight = "normal"
        self.textAlignment = "left"


@js(builtin=True)
class Button(View):
    tapEvent = js_str("tap")

    def __init__(self):
        super().__init__()
        self.text = ""
        self.fontSize = 14


@js(builtin=True)
class _Application:
    @js(inline="{self}.run({{ create: {create} }})")
    def run(self, create: callable) -> None: ...


Application = _Application()
js_object(Application, builtin=True)

__all__ = ["Application", "Button", "EventData", "Label", "Page", "StackLayout", "View"]
