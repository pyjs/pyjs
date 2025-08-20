import importlib
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

from pyjs.transpiler import prepare_bundle
from pyjs.transpiler.utils import SourceWriter
from pyjs.domx import HTMLElement, tag


def html(body, js, css, script_type):
    return tag('html',
        tag('head',
            tag("meta", {"charset": "utf-8"}),
            tag("link", {"rel": "stylesheet", "href": css}),
        ),
        tag('body', body),
        tag('script', {'type': script_type, 'src': js}, " ")
    )


def page(body, js, css, script_type="module"):
    src = SourceWriter()
    write(html(body, js, css, script_type), src)
    return src.getvalue()


def write(parent: HTMLElement, src):
    start = [f"<{parent.tagName.lower()}"]
    for attr_key, attr_val in parent.attributes.items():
        if attr_val is not None:
            start.append(f' {attr_key}="{attr_val}"')
    for attr_key, attr_val in parent.dataset.map.items():
        if attr_val is not None:
            start.append(f' data-{attr_key}="{attr_val}"')

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
        src.write_line(f"</{parent.tagName.lower()}>")
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
            self.wfile.write(page(
                server.get_html(),
                f'{self.server.entry_point.container.name}.js',
                'index.css'
            ).encode('utf-8'))
        elif self.path == '/index.css':
            self.send_response(200)
            self.send_header('Content-type', 'text/css')
            self.end_headers()
            self.wfile.write(server.get_css().encode('utf-8'))
        elif self.path.endswith('.js'):
            self.send_response(200)
            self.send_header('Content-type', 'application/javascript')
            self.end_headers()
            self.wfile.write(server.package[Path(self.path).stem])
        else:
            self.send_error(404)


class PyjsServer(HTTPServer):

    def __init__(self, module: str, css: str, entry_point: str, *entry_point_args):
        super().__init__(('', 8000), RequestHandler)
        self.module = importlib.import_module(module)
        self.module_name = module
        self.module_path = Path(self.module.__file__)
        self.module_last_modified = None
        self.package = None
        self.css_provided = bool(css)
        self.css = css
        self.entry_point = None
        self.entry_point_name = entry_point or "main"
        self.entry_point_args = entry_point_args
        self.refresh()

    def refresh(self):
        last_modified = self.module_path.stat().st_mtime
        if self.module_last_modified != last_modified:
            self.module_last_modified = last_modified
            importlib.reload(self.module)
            entry_point_py_func = getattr(self.module, self.entry_point_name)
            self.package, self.entry_point, css = prepare_bundle(entry_point_py_func)
            if not self.css_provided:
                self.css = css
            for package_name, js in self.package.items():
                self.package[package_name] = js.encode("utf-8")


    def get_html(self):
        return self.entry_point.py_func(*self.entry_point_args)

    def get_css(self):
        return self.css

    def serve_forever(self, poll_interval = 0.5):
        print("Serving on port 8000...")
        super().serve_forever(poll_interval)


def serve(module, css="", entry_point=None, *args):
    httpd = PyjsServer(module, css, entry_point, *args)
    httpd.serve_forever()
    #print(httpd.get_js(httpd.get_module()))
