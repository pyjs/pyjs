from pathlib import Path

from pyjs.server import serve

example_root = Path(__file__).parent
stylesheet = "\n".join(
    [
        (example_root / "base.css").read_text(),
        (example_root / "index.css").read_text(),
    ]
)
serve("pyjs_examples.todomvc.todomvc", stylesheet)
