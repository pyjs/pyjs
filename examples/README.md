# PyJS Examples

This directory is the source tree for the separately installable `pyjs-examples` distribution.
Setuptools maps this directory to the `pyjs_examples` import package, so the examples remain easy to
browse in the repository while installing as an ordinary top-level package.

From the repository root, install the core and examples from a source checkout:

```bash
python -m pip install -e . -e ./examples
```

An installed PyJS release provides the same package through the `examples` extra:

```bash
python -m pip install "pyjs[examples]"
```

Run any complete application as a module:

| Example | Command |
| --- | --- |
| [Calculator](calculator/) | `python -m pyjs_examples.calculator` |
| [Chatroom](chatroom/) | `python -m pyjs_examples.chatroom` |
| [Kanban board](kanban/) | `python -m pyjs_examples.kanban` |
| [NativeScript Counter](nativescript_counter/) | `python -m pyjs_examples.nativescript_counter` |
| [Space Invaders](space_invaders/) | `python -m pyjs_examples.space_invaders` |
| [TodoMVC](todomvc/) | `python -m pyjs_examples.todomvc` |
| [Component workspace](workspace/) | `python -m pyjs_examples.workspace` |
| [Component catalog](catalog.py) | `python -m pyjs_examples.catalog` |

List or copy examples using the core scaffolding command:

```bash
pyjs template
pyjs template pyjs_examples.calculator
pyjs create my-calculator --template pyjs_examples.calculator
pyjs create --single-file my_counter.py --template pyjs_examples.counter
```

The distribution registers modules and packages through the `pyjs.templates` entry-point group.
PyJS infers file and directory templates from normal Python module structure instead of hardcoding
a catalog.

The [focused samples](samples/) are small, executable sources intended for documentation excerpts
and `pyjs create PROJECT --template NAME`. The initial catalog includes
`pyjs_examples.samples.state_counter` and `pyjs_examples.samples.ui_dialog`.
