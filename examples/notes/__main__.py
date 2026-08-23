import os
import sys

if "--android" in sys.argv:
    from .notes import run

    run()
else:
    from pyjs.server.dev import serve

    from .web import render, save_order

    serve(
        "pyjs_examples.notes.web",
        render=render,
        routes={("POST", "/api/notes/order"): save_order},
        port=int(os.environ.get("PYJS_PORT", "8000")),
    )
