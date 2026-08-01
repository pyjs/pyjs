import os

from pyjs.server import serve

from .chatroom import render, websocket

serve(
    "pyjs_examples.chatroom.chatroom",
    render=render,
    websocket_routes={"/ws": websocket},
    port=int(os.environ.get("PYJS_PORT", "8000")),
)
