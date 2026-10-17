from pathlib import Path

import pytest

from pyjs.testing.helpers import analyze_file, transpile_file
from pyjs.tooling.node import Node


@pytest.mark.parametrize(
    "case_name",
    [
        "type_boolean",
        "type_numbers",
        "type_strings",
        pytest.param(
            "type_lists",
            marks=pytest.mark.skip(
                reason="Mixed list element types cannot yet be concatenated."
            ),
        ),
        "type_dicts",
    ],
)
def test_case(case_name):
    analyze_file(case_name)
    transpile_file(case_name)
    javascript = (
        Path(__file__).with_name("cases") / f"{case_name}.js"
    ).read_text(encoding="utf-8")
    syntax = Node().check_module(javascript)

    assert syntax.returncode == 0, syntax.stderr


#def test_classes(self):
#    self.analyze_file("classes", no_assert=True)
#    self.transpile_file("classes", no_assert=True)
#
#def test_inference(self):
#    self.analyze_file("inference", no_assert=True)
#    self.transpile_file("inference", no_assert=True)
#
#def test_attrs(self):
#    self.analyze_file('attrs')
#    self.transpile_file('attrs')
#
#def test_generics(self):
#    self.analyze_file('generics')
#    self.transpile_file("generics", no_assert=True)
