from pyjs import effect, js, nojs, state
from pyjs.web.domx import ProxyElement, button, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.network import Request, Response, fetch
from pyjs.web.serviceworker import (
    ExtendableEvent,
    FetchEvent,
    caches,
    navigator,
    service_worker_scope,
)
from pyjs.web.ui import Widget


@js
def calculate_result(left: float, right: float, operator: str) -> float:
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    return left / right


@js
async def install_app_shell(cache_name: str, assets: list[str]):
    cache = await caches.open(cache_name)
    await cache.addAll(assets)
    await service_worker_scope().skipWaiting()


@js
async def activate_app_shell():
    await service_worker_scope().clients.claim()


@js
async def cache_first(request: Request, cache_name: str) -> Response:
    cached = await caches.match(request)
    if cached is not None:
        return cached
    response = await fetch(request.url)
    cache = await caches.open(cache_name)
    await cache.put(request, response.clone())
    return response


@js
class InstallHandler:
    def __init__(self, cache_name: str, assets: list[str]):
        self.cache_name = cache_name
        self.assets = assets

    def handleEvent(self, event: ExtendableEvent):
        event.waitUntil(install_app_shell(self.cache_name, self.assets))


@js
class ActivateHandler:
    def handleEvent(self, event: ExtendableEvent):
        event.waitUntil(activate_app_shell())


@js
class FetchHandler:
    def __init__(self, cache_name: str):
        self.cache_name = cache_name

    def handleEvent(self, event: FetchEvent):
        if event.request.method == "GET":
            event.respondWith(cache_first(event.request, self.cache_name))


@js
def service_worker_main():
    cache_name = "pyjs-calculator-v1"
    scope = service_worker_scope()
    scope.addEventListener("install", InstallHandler(cache_name, ["/", "/index.css"]))
    scope.addEventListener("activate", ActivateHandler())
    scope.addEventListener("fetch", FetchHandler(cache_name))


@nojs
def service_worker_javascript(request):
    from pyjs.server.dev import Response
    from pyjs.transpiler import bundle

    source, _ = bundle(service_worker_main, include_main=True, include_css=False)
    return Response(
        source,
        content_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


@js
class CalculatorKeyListener:
    def __init__(self, app: CalculatorApp, kind: str, value: str):
        self.app = app
        self.kind = kind
        self.value = value

    async def handleEvent(self, event: Event):
        self.app.press(self.kind, self.value)
        if self.kind == "equals" and not self.app.error:
            await self.app.persist_result()


@js
class CalculatorKey(ProxyElement):
    def __init__(self, label: str, value: str, kind: str, wide: bool):
        attributes = {
            "aria-label": label,
            "data-key": value,
            "type": "button",
        }
        if wide:
            self.element = button(
                tw(
                    "col-span-2 h-12 rounded-xl bg-slate-100 px-5 text-left text-xl "
                    "font-medium text-slate-950 shadow-sm hover:bg-slate-200 "
                    "focus:outline-none focus:ring-2 focus:ring-slate-400"
                ),
                attributes,
                label,
            )
        elif kind == "operator" or kind == "equals":
            self.element = button(
                tw(
                    "h-12 rounded-xl bg-amber-500 text-xl font-semibold text-white shadow-sm "
                    "hover:bg-amber-600 focus:outline-none focus:ring-2 focus:ring-amber-400"
                ),
                attributes,
                label,
            )
        elif kind == "action":
            self.element = button(
                tw(
                    "h-12 rounded-xl bg-slate-200 text-lg font-medium text-slate-800 shadow-sm "
                    "hover:bg-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-400"
                ),
                attributes,
                label,
            )
        else:
            self.element = button(
                tw(
                    "h-12 rounded-xl bg-slate-100 text-xl font-medium text-slate-950 shadow-sm "
                    "hover:bg-slate-200 focus:outline-none focus:ring-2 focus:ring-slate-400"
                ),
                attributes,
                label,
            )

    def bind(self, app: CalculatorApp, kind: str, value: str):
        self.listener = CalculatorKeyListener(app, kind, value)
        self.element.addEventListener("click", self.listener)


@js
class CalculatorApp(Widget):
    display_value = state("0")
    stored_value = state(0.0)
    pending_operator = state("")
    replace_display = state(True)
    error = state(False)
    save_url = state("")
    service_worker_url = state("")

    def __init__(
        self,
        initial_value: str = "0",
        save_url: str = "",
        service_worker_url: str = "",
    ):
        super().__init__()
        self.display = ref(
            tag(
                "div",
                tw(
                    "min-h-20 overflow-hidden rounded-xl bg-slate-950 px-5 py-4 text-right "
                    "font-mono text-3xl font-semibold tracking-tight text-white"
                ),
                {
                    "aria-live": "polite",
                    "data-testid": "calculator-display",
                    "role": "status",
                },
                initial_value,
            )
        )
        self.display_value = initial_value
        self.save_url = save_url
        self.service_worker_url = service_worker_url

        self.clear_button = ref(CalculatorKey("AC", "clear", "action", False))
        self.clear_button.bind(self, "action", "clear")
        self.sign_button = ref(CalculatorKey("±", "sign", "action", False))
        self.sign_button.bind(self, "action", "sign")
        self.percent_button = ref(CalculatorKey("%", "percent", "action", False))
        self.percent_button.bind(self, "action", "percent")
        self.divide_button = ref(CalculatorKey("÷", "/", "operator", False))
        self.divide_button.bind(self, "operator", "/")
        self.seven_button = ref(CalculatorKey("7", "7", "digit", False))
        self.seven_button.bind(self, "digit", "7")
        self.eight_button = ref(CalculatorKey("8", "8", "digit", False))
        self.eight_button.bind(self, "digit", "8")
        self.nine_button = ref(CalculatorKey("9", "9", "digit", False))
        self.nine_button.bind(self, "digit", "9")
        self.multiply_button = ref(CalculatorKey("×", "*", "operator", False))
        self.multiply_button.bind(self, "operator", "*")
        self.four_button = ref(CalculatorKey("4", "4", "digit", False))
        self.four_button.bind(self, "digit", "4")
        self.five_button = ref(CalculatorKey("5", "5", "digit", False))
        self.five_button.bind(self, "digit", "5")
        self.six_button = ref(CalculatorKey("6", "6", "digit", False))
        self.six_button.bind(self, "digit", "6")
        self.subtract_button = ref(CalculatorKey("−", "-", "operator", False))
        self.subtract_button.bind(self, "operator", "-")
        self.one_button = ref(CalculatorKey("1", "1", "digit", False))
        self.one_button.bind(self, "digit", "1")
        self.two_button = ref(CalculatorKey("2", "2", "digit", False))
        self.two_button.bind(self, "digit", "2")
        self.three_button = ref(CalculatorKey("3", "3", "digit", False))
        self.three_button.bind(self, "digit", "3")
        self.add_button = ref(CalculatorKey("+", "+", "operator", False))
        self.add_button.bind(self, "operator", "+")
        self.zero_button = ref(CalculatorKey("0", "0", "digit", True))
        self.zero_button.bind(self, "digit", "0")
        self.decimal_button = ref(CalculatorKey(".", ".", "decimal", False))
        self.decimal_button.bind(self, "decimal", ".")
        self.equals_button = ref(CalculatorKey("=", "=", "equals", False))
        self.equals_button.bind(self, "equals", "=")
        keys: list[CalculatorKey] = [
            self.clear_button,
            self.sign_button,
            self.percent_button,
            self.divide_button,
            self.seven_button,
            self.eight_button,
            self.nine_button,
            self.multiply_button,
            self.four_button,
            self.five_button,
            self.six_button,
            self.subtract_button,
            self.one_button,
            self.two_button,
            self.three_button,
            self.add_button,
            self.zero_button,
            self.decimal_button,
            self.equals_button,
        ]
        card = tag(
            "main",
            tw("w-full max-w-sm rounded-3xl border border-slate-200 bg-white p-4 shadow-xl"),
            {"data-testid": "calculator-card"},
            tag(
                "header",
                tw("mb-4 flex items-end justify-between px-1"),
                tag("h1", tw("text-lg font-semibold text-slate-950"), "Calculator"),
                tag(
                    "span",
                    tw("text-xs font-medium uppercase tracking-widest text-slate-400"),
                    "PyJS",
                ),
            ),
            self.display,
            tag("div", tw("mt-4 grid grid-cols-4 gap-2"), *keys),
        )
        self.add(
            tw("box-border flex min-h-screen items-center justify-center bg-slate-100 p-4"),
            card,
        )

    async def initialize(self):
        if self.service_worker_url == "":
            return
        registration = await navigator.serviceWorker.register(self.service_worker_url)
        self.set_data("service-worker", registration.scope)

    @effect(display_value)
    def render_display(self):
        self.display.textContent = self.display_value

    def clear(self):
        self.display_value = "0"
        self.stored_value = 0.0
        self.pending_operator = ""
        self.replace_display = True
        self.error = False

    def value(self) -> float:
        if self.error:
            return 0.0
        return float(self.display_value)

    def input_digit(self, digit: str):
        if self.error:
            self.clear()
        if self.replace_display or self.display_value == "0":
            self.display_value = digit
            self.replace_display = False
        else:
            self.display_value += digit

    def input_decimal(self):
        if self.error:
            self.clear()
        if self.replace_display:
            self.display_value = "0."
            self.replace_display = False
        elif len(self.display_value.split(".")) == 1:
            self.display_value += "."

    def toggle_sign(self):
        value = self.display_value
        if self.error or value == "0" or value == "0.0":
            return
        self.display_value = str(0.0 - float(value))

    def percent(self):
        if self.error:
            return
        self.display_value = str(float(self.display_value) / 100.0)
        self.replace_display = True

    def choose_operator(self, operator: str):
        if self.error:
            return
        if self.pending_operator != "" and not self.replace_display:
            self.calculate()
            if self.error:
                return
        self.stored_value = float(self.display_value)
        self.pending_operator = operator
        self.replace_display = True

    def calculate(self) -> float:
        operator = self.pending_operator
        if self.error or operator == "":
            return self.value()
        right = float(self.display_value)
        if operator == "/" and right == 0.0:
            self.display_value = "Error"
            self.pending_operator = ""
            self.replace_display = True
            self.error = True
            return 0.0
        result = calculate_result(self.stored_value, right, operator)
        self.display_value = str(result)
        self.stored_value = result
        self.pending_operator = ""
        self.replace_display = True
        return result

    async def persist_result(self):
        if self.save_url == "":
            return
        await fetch(
            self.save_url,
            {
                "method": "POST",
                "headers": {"Content-Type": "text/plain"},
                "body": self.display_value,
                "keepalive": True,
            },
        )

    def press(self, kind: str, value: str):
        if kind == "digit":
            self.input_digit(value)
        elif kind == "decimal":
            self.input_decimal()
        elif kind == "operator":
            self.choose_operator(value)
        elif kind == "equals":
            self.calculate()
        elif value == "clear":
            self.clear()
        elif value == "sign":
            self.toggle_sign()
        else:
            self.percent()


def main(
    initial_value: str = "0",
    save_url: str = "",
    service_worker_url: str = "",
):
    return CalculatorApp(
        initial_value=initial_value,
        save_url=save_url,
        service_worker_url=service_worker_url,
    )


@nojs
def render(request):
    return main(
        request.session.get("last_result", "0"),
        "/api/calculator/result",
        "/calculator-serviceworker.js",
    )


@nojs
def save_result(request):
    import math

    result = request.body.decode("utf-8")
    if len(result) > 32:
        raise ValueError("result must be a short numeric string")
    if not math.isfinite(float(result)):
        raise ValueError("result must be finite")
    request.session["last_result"] = result


if __name__ == "__main__":
    import os

    from pyjs.server.dev import serve

    serve(
        "calculator",
        render=render,
        routes={
            ("POST", "/api/calculator/result"): save_result,
            ("GET", "/calculator-serviceworker.js"): service_worker_javascript,
        },
        port=int(os.environ.get("PYJS_PORT", "8000")),
    )
