import pytest

from pyjs.web.ssr import render_html
from pyjs.web.ui.image_preview import ImagePreview


@pytest.mark.parametrize("options", [
    {"ratio": 0}, {"ratio": -1}, {"ratio": float("nan")}, {"ratio": float("inf")},
    {"max_width": 0}, {"max_height": -1}, {"fit": "stretch"},
])
def test_preview_rejects_invalid_layout_options(options):
    with pytest.raises(ValueError):
        ImagePreview(alt="Image", **options)


def test_ssr_preview_keeps_layout_and_accessibility_without_loading_source_bytes():
    preview = ImagePreview(alt="Receipt <2026>", ratio=2.0, fit="cover", max_width=800, max_height=400)
    markup = render_html(preview)
    assert 'data-slot="image-preview"' in markup
    assert 'data-fit="cover"' in markup
    assert 'aspect-ratio: 2.0' in markup
    assert 'data-max-width="800"' in markup
    assert 'data-max-height="400"' in markup
    assert 'alt="Receipt &lt;2026&gt;"' in markup
    assert 'aria-label="Retry loading image"' in markup
    assert 'src=' not in markup
