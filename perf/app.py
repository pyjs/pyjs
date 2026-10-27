"""Live performance UI, usable standalone or mounted in docs/website servers."""
import json
import re
from pathlib import Path

from perf.page import main
from perf.view import view
from pyjs.javascript.transpiler import bundle_with_source_map
from pyjs.server import page
from pyjs.server.dev import Application, Response
from pyjs.web.domx import tag

ROOT = Path(__file__).resolve().parent


def snapshots(root):
    found = []
    if root.exists():
        for directory in root.iterdir():
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", directory.name) and directory.is_dir():
                source = directory / "results.json"
                if source.is_file() and source.resolve().is_relative_to(root.resolve()):
                    found.append((directory.name, json.loads(source.read_text())))
    return sorted(found, key=lambda item: (item[1]["created"], item[0]), reverse=True)


def mount(application, *, root=None, prefix="/perf/"):
    root = Path(root) if root is not None else ROOT / "runs"
    prefix = "/" + prefix.strip("/") + "/"
    generated, _ = bundle_with_source_map(main, include_main=True, include_css=False, filename="perf.js")

    @application.get(prefix + "page.js")
    def javascript(request):
        return Response(generated.javascript, content_type="application/javascript")

    @application.get(prefix + "style.css")
    def style(request):
        return Response((ROOT / "style.css").read_text(), content_type="text/css")

    @application.get(prefix)
    def index(request):
        available = snapshots(root)
        selected = request.query_value("run")
        chosen = next((item for item in available if item[0] == selected), None) if selected else next(iter(available), None)
        if chosen:
            body = view(chosen[1], [item[0] for item in available], chosen[0], prefix)
            status = 200
        else:
            body = tag("main", tag("h1", "PyJS performance lab"),
                       tag("p", "Snapshot not found." if selected else "No snapshots yet. Run python -m perf.run to record one."))
            status = 404 if selected else 200
        return Response.html(page(body, prefix + "page.js", prefix + "style.css", title="PyJS performance lab"),
                             status=status, headers={"Cache-Control": "no-store"})

    @application.get(prefix + "results/{name}.json")
    def results(request, name):
        data = next((data for run, data in snapshots(root) if run == name), None)
        return Response.json(data, headers={"Cache-Control": "no-store"}) if data is not None else Response.text("Not found", status=404)

    @application.get(prefix + "artifact/{name}/{path:path}")
    def artifact(request, name, path):
        data = next((data for run, data in snapshots(root) if run == name), None)
        allowed = data is not None and any(path in row.get("artifacts", {}) for row in data["rows"])
        candidate = (root / name / path).resolve()
        if (not allowed or not candidate.is_relative_to((root / name).resolve()) or
                not candidate.is_relative_to(root.resolve()) or candidate.suffix not in {".js", ".ll", ".txt", ".xml", ".log"} or not candidate.is_file()):
            return Response.text("Not found", status=404)
        return Response(candidate.read_bytes(), headers={"X-Content-Type-Options": "nosniff"})


def create_app():
    app = Application(name="PyJS performance lab")
    app.get("/", lambda request: Response.redirect("/perf/"))
    mount(app)
    return app
