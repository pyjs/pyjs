import argparse
import os

parser = argparse.ArgumentParser(description="Run the Calculator example.")
parser.add_argument("--android", action="store_true", help="Build and run the Android APK")

if parser.parse_args().android:
    from .android_build import run_android

    run_android()
else:
    from pyjs.server.dev import serve

    from .calculator import render, save_result, service_worker_javascript

    serve(
        "pyjs_examples.calculator.calculator",
        render=render,
        routes={
            ("POST", "/api/calculator/result"): save_result,
            ("GET", "/calculator-serviceworker.js"): service_worker_javascript,
        },
        port=int(os.environ.get("PYJS_PORT", "8000")),
    )
