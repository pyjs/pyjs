# Chat Example

This example combines a polished, Slack-like workspace with an AI assistant
conversation. It demonstrates:

- HTTP and WebSockets served on the same port
- a shared typed protocol validated at the server boundary
- a display name stored per browser tab with `sessionStorage`
- public room creation and room switching
- real-time messages and room presence
- a local assistant preview with structured questions and generated artifacts
- server-owned Free/Pro membership broadcast to every connected client
- DOM-owned scalar state declared with `state()` and focused effects
- message and presence collections rendered explicitly from server snapshots
- composition of `Message`, `Bubble`, `MessageScroller`, `Questionnaire`,
  `Attachment`, `Marker`, `Avatar`, `Badge`, `Button`, `Empty`, and
  `InputGroup`
- entirely in-memory server state that resets on restart

See [Agent conversation patterns](AI_ELEMENTS.md) for reusable AI UI
compositions and their transport boundaries.

## Architecture

Chat deliberately uses the native browser `WebSocket` rather than hiding an
ordered, bidirectional message stream behind the resource API:

- `protocol.py` defines the commands, snapshots, and chat messages shared by
  the Python server and transpiled browser client;
- `chat_server.py` validates every incoming frame with Pydantic before it
  changes server-owned rooms, messages, presence, or membership; and
- `chat.py` uses `pyjs.web.network.WebSocket` directly and renders typed
  snapshots into DOM-owned UI state.

This is the low-level complement to Store's generated RPC and live-query
example. Applications can use raw WebSockets for chat, signaling, games, or
existing protocols without opting out of PyJS models, components, or tests.

## Run the chat

From the repository root:

```bash
uv run python -m pyjs_examples.chat
```

Open `http://127.0.0.1:8000/` in two tabs, choose a different display name in
each, and join the same room. Select **PyJS Assistant** in the sidebar to try
the local agent-style conversation without configuring an API key. Select
**Upgrade** below the profile to change the server-owned workspace plan for
every connected member.

## Run the tests

Run the Python server tests:

```bash
uv run pytest -q examples/chat/tests
```

Run the custom-element UI tests in the browser:

```bash
uv run pytest -q examples/chat/tests --pyjs-target=web \
  --pyjs-browser=managed
```

## Run the visual test

The visual test starts its own chat server, opens two headless browser tabs
as Alice and Bob, has them create a room and exchange messages, and verifies
that presence updates when Bob leaves:

```bash
uv run python examples/chat/visual_test.py
```

It writes both browser views and a JSON state report to `screenshots/`. The
chat app does not need to be running beforehand.
