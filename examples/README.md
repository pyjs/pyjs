# PyJS Examples

This directory is the source tree for the separately installable
`pyjs-examples` distribution. Setuptools maps it to the `pyjs_examples` import
package while keeping each application easy to browse in the repository.

Install the core and examples from a source checkout:

```bash
uv sync
```

An installed release provides the examples through an extra:

```bash
python -m pip install "pyjs[examples]"
```

## Application responsibilities

The examples progress from small programs to composed, full-stack systems.
Features may overlap when that makes an application more realistic.

| Example | Role | Principal PyJS coverage |
| --- | --- | --- |
| [Counter](counter.py) | Smallest app | DOM, events, one-file tests |
| [Calculator](calculator/) | Universal app | Web, PWA, Android, SSR, state |
| [Components](components/) | UI reference | Widgets, forms, navigation |
| [Notes](notes/) | Personal app | Web, Android, drag/drop, restore |
| [Chat](chat/) | Real-time starter | WebSockets, multi-window, plans |
| [Store](store/) | Business app | Django, JSON:API, SSE, themes, cursor feeds |
| [Space Invaders](space_invaders/) | GPU game | WebGPU, input, render tests |

Run an application with its module name, for example:

```bash
python -m pyjs_examples.calculator
python -m pyjs_examples.components
python -m pyjs_examples.notes
python -m pyjs_examples.chat
python -m pyjs_examples.store
```

Install `pyjs-examples[store]` before running Store from a release package.

Calculator and Notes accept `--android` to build and launch their NativeScript
versions. Their default command serves the web version.

Components is also the source and test surface for the planned website
component reference. It combines the former catalog, workspace, navigation,
and focused dialog sample in one application.

Notes combines the former Kanban board with the mobile notes application. It
uses DOM-owned ordering, drag/drop, server restoration, and visual tests.

Store is the canonical Django and typed client/server example. It also owns the
themability story, signed cursor feeds, infinite scrolling, and data-driven
charts.

## Templates

List, inspect, or copy examples using the core scaffolding command:

```bash
pyjs template
pyjs template pyjs_examples.calculator
pyjs create my-calculator --template pyjs_examples.calculator
pyjs create --single-file my_counter.py --template pyjs_examples.counter
```

The distribution registers modules and packages through the `pyjs.templates`
entry-point group. PyJS infers file and directory templates from normal Python
module structure instead of hardcoding a catalog.
