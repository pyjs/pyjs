import importlib
from http.server import HTTPServer, BaseHTTPRequestHandler

from pyjs.transpiler import transpile
from pyjs.transpiler.utils import SourceWriter
from pyjs.dom import HTMLElement


def tag(name: str, attrs: dict = None, children: list = None):
    e = HTMLElement()
    e.tagName = name
    e.attributes = attrs or {}
    e.children = children or []
    return e


def html(body, js):
    return tag('html', {}, [
        tag('head', {}, [
            tag("meta", {"charset": "utf-8"}),
            tag("link", {"rel": "stylesheet", "href": "index.css"}),
        ]),
        tag('body', {}, [body]),
        tag('script', {'src': js}, [" "])
    ])


def page(body, js):
    src = SourceWriter()
    write(html(body, js), src)
    return src.getvalue()


def write(parent: HTMLElement, src):
    start = [f"<{parent.tagName}"]
    for attr_key, attr_val in parent.attributes.items():
        start.append(f' {attr_key}="{attr_val}"')

    if parent.children:
        start.append(">")
        src.write_line("".join(start))
        src.indent()
        for child in parent.children:
            if isinstance(child, HTMLElement):
                write(child, src)
            else:
                assert isinstance(child, str), f"Child is of type {type(child)}."
                src.write_line(child)
        src.dedent()
        src.write_line(f"</{parent.tagName}>")
    else:
        start.append("/>")
        src.write_line("".join(start))


class RequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        server: PyjsServer = self.server
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            module = server.get_module()
            self.wfile.write(page(server.get_dom(module), 'main.js').encode('utf-8'))
        elif self.path == '/index.css':
            self.send_response(200)
            self.send_header('Content-type', 'text/css')
            self.end_headers()
            self.wfile.write(server.get_css().encode('utf-8'))
        elif self.path == '/main.js':
            self.send_response(200)
            self.send_header('Content-type', 'application/javascript')
            self.end_headers()
            module = server.get_module()
            self.wfile.write(server.get_js(module).encode('utf-8'))
        else:
            self.send_error(404)


class PyjsServer(HTTPServer):

    def __init__(self, module: str, client: str, css: str, ssr: str, *ssr_args):
        super().__init__(('', 8000), RequestHandler)
        self.module = importlib.import_module(module)
        self.client_entry_point = client
        self.css = css
        self.ssr_entry_point = ssr
        self.ssr_entry_point_args = ssr_args

    def get_module(self):
        importlib.reload(self.module)
        return self.module

    def get_dom(self, module):
        return getattr(module, self.ssr_entry_point)(*self.ssr_entry_point_args)

    def get_js(self, module):
        entry_point = getattr(module, self.client_entry_point)
        js = transpile(entry_point)+f"\n\n{self.client_entry_point}();\n"
        return js

    def get_css(self):
        return self.css

    def serve_forever(self, poll_interval = 0.5):
        print("Serving on port 8000...")
        super().serve_forever(poll_interval)


def serve(module, client_entry_point, css, ssr_entry_point, *args):
    httpd = PyjsServer(module, client_entry_point, css, ssr_entry_point, *args)
    httpd.serve_forever()
