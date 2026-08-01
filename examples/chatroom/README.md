# Chatroom Example

This example is a small Slack-like workspace built with PyJS custom elements.
It demonstrates:

- HTTP and WebSockets served on the same port
- a display name stored per browser tab with `sessionStorage`
- public room creation and room switching
- real-time messages and room presence
- DOM-owned scalar state declared with `state()` and rendered with focused effects
- message and presence collections rendered explicitly from server snapshots
- entirely in-memory server state that resets on restart

## Run the chatroom

From the repository root:

```bash
.venv/bin/python -m pyjs_examples.chatroom
```

Open `http://127.0.0.1:8000/` in two tabs, choose a different display name in
each, and join the same room.

## Run the tests

Run the Python server tests:

```bash
.venv/bin/python -m pytest -q examples/chatroom/tests
```

Run the custom-element UI tests in the browser:

```bash
.venv/bin/python -m pytest -q examples/chatroom/tests --pyjs-target=web
```

## Run the visual test

The visual test starts its own chatroom server, opens two headless browser tabs
as Alice and Bob, has them create a room and exchange messages, and verifies
that presence updates when Bob leaves:

```bash
.venv/bin/python examples/chatroom/visual_test.py
```

It writes both browser views and a JSON state report to `screenshots/`. The
chatroom does not need to be running beforehand.
