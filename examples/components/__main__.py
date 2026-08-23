import os

from pyjs.server.dev import serve

from .app import (
    catalog_page,
    catalog_view,
    layout,
    workspace_page,
    workspace_view,
)

serve(
    "pyjs_examples.components.app",
    routes={
        ("GET", "/"): catalog_page,
        ("GET", "/workspace"): workspace_page,
    },
    layout=layout,
    layout_id="components",
    page_entry_points=(catalog_view, workspace_view),
    port=int(os.environ.get("PYJS_PORT", "8000")),
)
