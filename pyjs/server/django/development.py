import asyncio
import json
import time
from secrets import token_urlsafe

from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse
from django.views.decorators.http import require_safe

DEVELOPMENT_RELOAD_HEADER = "X-PyJS-Generation"
DEVELOPMENT_RELOAD_INTERVAL_SECONDS = 1.0
_generation = token_urlsafe(18)


class DevelopmentReloadApplication:
    def __init__(self, application, path: str):
        self.application = application
        self.path = path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket" or scope["path"] != self.path:
            await self.application(scope, receive, send)
            return
        if not settings.DEBUG:
            await send({"type": "websocket.close", "code": 1008})
            return
        message = await receive()
        if message["type"] != "websocket.connect":
            return
        await send({"type": "websocket.accept"})
        await send(
            {
                "type": "websocket.send",
                "text": json.dumps(_generation),
            }
        )
        while True:
            message = await receive()
            if message["type"] == "websocket.disconnect":
                return


def development_reload_application(application, path: str):
    """Add a cooperative ASGI WebSocket for the development reload client."""
    return DevelopmentReloadApplication(application, path)


def _development_reload_event():
    return f"event: generation\ndata: {json.dumps(_generation)}\n\n"


async def _development_reload_events():
    yield "retry: 500\n\n"
    while True:
        yield _development_reload_event()
        await asyncio.sleep(DEVELOPMENT_RELOAD_INTERVAL_SECONDS)


def _sync_development_reload_events():
    yield "retry: 500\n\n"
    while True:
        yield _development_reload_event()
        time.sleep(DEVELOPMENT_RELOAD_INTERVAL_SECONDS)


@require_safe
def development_reload_script(request):
    """Serve a development-only client that reloads after a server restart."""
    if not settings.DEBUG:
        return HttpResponse(status=404)
    if "events" in request.GET:
        events = (
            _development_reload_events()
            if hasattr(request, "scope")
            else _sync_development_reload_events()
        )
        response = StreamingHttpResponse(
            events,
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, no-transform",
                "X-Accel-Buffering": "no",
                DEVELOPMENT_RELOAD_HEADER: _generation,
            },
        )
        return response
    generation = json.dumps(_generation)
    source = f"""const generation = {generation};
let fallbackStarted = false;

function generationChanged(value) {{
  if (value !== generation) {{
    window.location.reload();
    return true;
  }}
  return false;
}}

function startEventSource() {{
  if (fallbackStarted) {{
    return;
  }}
  fallbackStarted = true;
  const eventsUrl = new URL(import.meta.url);
  eventsUrl.searchParams.set("events", "");
  const source = new EventSource(eventsUrl);
  source.addEventListener("generation", (event) => {{
    if (generationChanged(JSON.parse(event.data))) {{
      source.close();
    }}
  }});
}}

function connectSocket() {{
  const socketUrl = new URL(import.meta.url);
  socketUrl.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(socketUrl);
  let opened = false;
  socket.addEventListener("open", () => {{
    opened = true;
  }});
  socket.addEventListener("message", (event) => {{
    generationChanged(JSON.parse(event.data));
  }});
  socket.addEventListener("close", () => {{
    if (opened) {{
      window.setTimeout(connectSocket, 500);
    }} else {{
      startEventSource();
    }}
  }});
}}

connectSocket();
"""
    return HttpResponse(
        source,
        content_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            DEVELOPMENT_RELOAD_HEADER: _generation,
        },
    )
