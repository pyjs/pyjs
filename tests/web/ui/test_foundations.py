import pytest

from pyjs.web.ui.alert import Alert, AlertDescription, AlertTitle
from pyjs.web.ui.badge import Badge
from pyjs.web.ui.separator import Separator
from pyjs.web.ui.skeleton import Skeleton


@pytest.mark.pyjs_python
def test_foundation_widgets_render_semantic_attributes_on_the_server():
    alert = Alert(AlertTitle("Problem"), AlertDescription("Try again."), variant="destructive")
    badge = Badge("Beta", variant="secondary")
    separator = Separator("vertical", decorative=False)
    skeleton = Skeleton("2rem", "2rem")

    assert alert.getAttribute("role") == "alert"
    assert alert.getAttribute("data-variant") == "destructive"
    assert badge.getAttribute("data-variant") == "secondary"
    assert separator.getAttribute("role") == "separator"
    assert separator.getAttribute("aria-orientation") == "vertical"
    assert skeleton.getAttribute("aria-hidden") == "true"
