# Void Patrol

Void Patrol is a compact Space Invaders-style WebGPU game implemented in
Python and transpiled to JavaScript by PyJS.

It demonstrates:

- deterministic game-state updates that run in Python and JavaScript
- a WebGPU renderer using dynamic vertex buffers and direction-aware,
  depth-tested geometry
- keyboard controls and a request-animation-frame game loop
- score, lives, wave progression, collisions, and restart behavior
- observable summary state mirrored onto custom-element DOM attributes
- browser render regression testing against a stored PNG

## Run the game

From the repository root:

```bash
python -m pyjs_examples.space_invaders
```

Open `http://127.0.0.1:8000/`. Move with the arrow keys or A/D, fire with Space,
and press Enter to restart after game over.

## Run the tests

Run the deterministic state tests with Python:

```bash
python -m pytest -q examples/space_invaders/tests
```

Run the same tests and the WebGPU render test in a browser:

```bash
python -m pytest -q examples/space_invaders/tests --pyjs-target=web
```

To create or intentionally replace the expected render:

```bash
python -m pytest -q examples/space_invaders/tests/test_browser_game.py \
  --pyjs-target=web --pyjs-update-renders
```
