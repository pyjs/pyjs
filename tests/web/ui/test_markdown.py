from pyjs.web.ssr import render_html
from pyjs.web.ui.markdown import Markdown


def test_server_markdown_updates_remain_escaped_text():
    message = Markdown("Old")
    source = '**Latest** <img src="https://example.com/track"> & text'
    message.set_text(source)
    rendered = render_html(message)

    assert message.body.textContent == source
    assert message.get_data("source") == source
    assert "<img" not in rendered
    assert "<strong>" not in rendered
    assert "**Latest** &lt;img" in rendered
    assert "&amp; text" in rendered
