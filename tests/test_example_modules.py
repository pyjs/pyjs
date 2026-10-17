import importlib

import pytest

from pyjs.javascript.transpiler import bundle
from pyjs.tooling.node import Node

WEB_EXAMPLES = (
    "examples.calculator.calculator",
    "examples.chat.chat",
    "examples.components.app",
    "examples.counter",
    "examples.notes.web",
    "examples.space_invaders.space_invaders",
)


@pytest.mark.parametrize("module_name", WEB_EXAMPLES)
def test_web_example_bundle_is_valid_ecmascript(module_name):
    module = importlib.import_module(module_name)
    javascript, _ = bundle(module.main, include_main=True)

    result = Node().check_module(javascript)

    assert result.returncode == 0, result.stderr
