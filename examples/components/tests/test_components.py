import ast
import re
from pathlib import Path

from pyjs.server import NavigationPage
from pyjs.web.ssr import render_html
from pyjs_examples.components.app import (
    ComponentsApp,
    catalog_page,
    catalog_view,
    main,
    workspace_page,
)
from pyjs_examples.components.catalog import CATALOG_DARK_STYLES, CatalogApp
from pyjs_examples.components.catalog_sources import catalog_source
from pyjs_examples.components.workspace import WorkspaceApp

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_LINK = re.compile(
    r'href="https://github.com/pyjs/pyjs/blob/main/pyjs/web/ui/([^"/]+)\.py"'
)


def test_components_renders_catalog_inside_the_persistent_layout():
    application = main()
    catalog = catalog_view()

    assert isinstance(application, ComponentsApp)
    assert isinstance(catalog, CatalogApp)
    assert application.outlet.get_data("layout") == "components"
    rendered = render_html(application)
    assert "Show notification" in rendered
    assert 'data-slot="toast"' not in rendered
    assert "pyjs.web.ui.button" in rendered
    assert "View Python source" in rendered
    assert rendered.count('data-catalog-source=""') == rendered.count(
        'data-catalog-component="'
    )
    assert rendered.count('data-catalog-copy=""') == rendered.count(
        'data-catalog-component="'
    )
    assert rendered.count("Testing guidance") == rendered.count(
        'data-catalog-component="'
    )
    assert "Slider(45, minimum=0, maximum=100, label='Volume')" in rendered
    assert "Accessibility" in rendered
    assert "prefers-color-scheme: dark" in CATALOG_DARK_STYLES
    assert 'data-pyjs-navigation-link="" href="/">Catalog</a>' in rendered
    assert (
        'data-pyjs-navigation-link="" href="/workspace">Workspace block</a>'
        in rendered
    )
    source_links = SOURCE_LINK.findall(rendered)
    source_modules = set(source_links)
    assert len(source_links) == rendered.count('data-catalog-component="')
    assert not [
        module
        for module in source_modules
        if not (PROJECT_ROOT / "pyjs" / "web" / "ui" / f"{module}.py").is_file()
    ]
    component_ids = re.findall(r'data-catalog-component="([^"]+)"', rendered)
    assert all(
        component_id == "dialog" or catalog_source(component_id) != ""
        for component_id in component_ids
    )
    assert [
        component_id
        for component_id in component_ids
        if component_id != "dialog"
        and not _is_valid_python(catalog_source(component_id))
    ] == []


def _is_valid_python(source: str) -> bool:
    try:
        ast.parse(source)
    except SyntaxError:
        return False
    return True


def test_component_routes_return_independent_navigation_pages():
    catalog = catalog_page(None)
    workspace = workspace_page(None)

    assert isinstance(catalog, NavigationPage)
    assert isinstance(catalog.body, CatalogApp)
    assert catalog.title == "Components · PyJS"
    assert isinstance(workspace.body, WorkspaceApp)
    assert workspace.title == "Workspace block · Components · PyJS"
