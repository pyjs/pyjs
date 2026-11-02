import pytest

from tests.semantics.helpers import run_javascript


@pytest.mark.parametrize("scenario", ["editing_workflow", "geometry_contract", "viewport_contract", "layout_contract"])
def test_diagram_javascript_contract(scenario):
    result, _ = run_javascript(f'''
from pyjs import js
from tests.diagram_cases import {scenario}
@js
def main() -> None:
    {scenario}()
    print("verified")
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "verified"
