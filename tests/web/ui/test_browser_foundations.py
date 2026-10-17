import pytest

from pyjs import js
from pyjs.web.ui.alert import Alert, AlertDescription, AlertTitle
from pyjs.web.ui.badge import Badge
from pyjs.web.ui.separator import Separator
from pyjs.web.ui.skeleton import Skeleton
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


@js
def test_foundation_widgets_render_variants_and_visual_dimensions():
    alert = Alert(AlertTitle("Problem"), AlertDescription("Try again."), variant="destructive")
    badge = Badge("Preview", variant="outline")
    separator = Separator()
    skeleton = Skeleton("12rem", "1rem")
    mount(alert, badge, separator, skeleton)

    assert alert.getAttribute("role") == "alert"
    assert alert.getAttribute("data-variant") == "destructive"
    assert badge.getAttribute("data-variant") == "outline"
    assert separator.getAttribute("data-orientation") == "horizontal"
    assert separator.getAttribute("role") == "none"
    assert skeleton.getAttribute("aria-hidden") == "true"

    bounds = skeleton.getBoundingClientRect()
    assert round(bounds.height) == 16
    assert round(bounds.width) == 192
