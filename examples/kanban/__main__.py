import os

from pyjs.server import serve

serve(
    "pyjs_examples.kanban.kanban",
    port=int(os.environ.get("PYJS_PORT", "8000")),
)
