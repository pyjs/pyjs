import argparse
import os

parser = argparse.ArgumentParser(description="Run the Notes example.")
parser.add_argument("--android", action="store_true", help="Build and run the Android APK")

if parser.parse_args().android:
    from .android_build import run_android

    run_android()
else:
    from pyjs.server.dev import serve

    from .web import render, save_order

    serve(
        "pyjs_examples.notes.web",
        render=render,
        routes={("POST", "/api/notes/order"): save_order},
        port=int(os.environ.get("PYJS_PORT", "8000")),
    )
