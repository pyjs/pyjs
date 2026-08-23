import os

from pyjs.server.dev import serve

from .chat import render, websocket

serve(
    "pyjs_examples.chat.chat",
    render=render,
    websocket_routes={"/ws": websocket},
    port=int(os.environ.get("PYJS_PORT", "8000")),
)
