import os
import sys

from pyjs.server.dev import serve

from .calculator import render, save_result, service_worker_javascript

if "--android" in sys.argv:
    from .android import run_android

    run_android()
else:
    serve(
        "pyjs_examples.calculator.calculator",
        render=render,
        routes={
            ("POST", "/api/calculator/result"): save_result,
            ("GET", "/calculator-serviceworker.js"): service_worker_javascript,
        },
        port=int(os.environ.get("PYJS_PORT", "8000")),
    )
