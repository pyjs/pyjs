from pyjs.web.ssr import render_html
from pyjs.web.ui.button import Button
from pyjs.web.ui.theme import Theme, ThemeProvider


def test_theme_serializes_semantic_tokens_and_scoped_styles():
    theme = Theme("orchard", primary="#166534", radius="1rem")

    assert theme.style() == (
        "--pyjs-background:#f8fafc;"
        "--pyjs-foreground:#020617;"
        "--pyjs-surface:#ffffff;"
        "--pyjs-surface-foreground:#020617;"
        "--pyjs-primary:#166534;"
        "--pyjs-primary-hover:#1e293b;"
        "--pyjs-primary-foreground:#ffffff;"
        "--pyjs-muted:#f1f5f9;"
        "--pyjs-muted-foreground:#64748b;"
        "--pyjs-border:#cbd5e1;"
        "--pyjs-ring:#94a3b8;"
        "--pyjs-radius:1rem"
    )

    source = render_html(ThemeProvider(theme, Button("Save")))

    # The complete CSS is intentionally substantial; these assertions verify
    # the provider boundary and representative component selectors.
    assert source.startswith(
        '<div data-pyjs-theme="orchard" style="--pyjs-background:#f8fafc;'
    )
    assert '[data-pyjs-theme] [data-slot="button"]' in source
    assert 'data-slot="button" data-variant="default"' in source
