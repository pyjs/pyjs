import pytest

from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT


@pytest.mark.parametrize("expression", ["repr(view)", "view.__repr__()", 'f"{view!r}"', "format(view)"])
@pytest.mark.parametrize("retains", [False, True])
def test_nested_view_formatting_retains_only_effectful_callbacks(expression, retains):
    with analyze_source(f'''
        from collections.abc import ValuesView
        from pyjs.native import gc_pin

        class Label:
            def __repr__(self) -> str:
                {"gc_pin(self)" if retains else "pass"}
                return "label"

        def main(view: ValuesView[list[Label]]) -> str:
            return {expression}
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.entry_point.ir.lifetime.external_parameters == ({"view"} if retains else set())


def test_view_formatting_uses_reached_override_lifetimes():
    with analyze_source('''
        from collections.abc import ValuesView
        from pyjs.native import gc_pin

        class Label:
            def __repr__(self) -> str:
                return "base"

        class Retained(Label):
            def __repr__(self) -> str:
                gc_pin(self)
                return "child"

        def format_values(view: ValuesView[Label]) -> str:
            return repr(view)

        def main() -> str:
            values: dict[int, Label] = {1: Retained()}
            return format_values(values.values())
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        target = analysis.entry_point.container.search("format_values")
        assert target.ir.lifetime.external_parameters == {"view"}
