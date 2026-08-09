import pytest
from pyjs_examples.navigation.navigation import (
    AtlasLayout,
    PreferencesPanel,
    analytics_page,
    calendar_page,
    main,
    messages_page,
    overview_page,
    projects_page,
    reports_page,
    settings_page,
    settings_view,
    team_page,
)

pytestmark = pytest.mark.pyjs_python


def test_navigation_example_renders_a_persistent_shell_and_initial_page():
    application = main()

    assert isinstance(application, AtlasLayout)
    assert application.get_data("navigation-count") == "0"
    navigation = application.sidebar.children[1]
    assert len(navigation.children) == 8
    assert application.outlet.get_data("layout") == "atlas"
    initial_page = application.outlet.children[0].children[0]
    assert initial_page.children[0].children[1].childNodes[0].data == "Good morning, Lex"


def test_settings_page_contains_an_interactive_custom_element():
    content = settings_view()
    preferences = content.children[1].children[0]

    assert isinstance(preferences, PreferencesPanel)
    assert preferences.get_data("digest") == "enabled"
    assert preferences.state.childNodes[0].data == "Enabled"


@pytest.mark.parametrize(
    ("renderer", "title", "heading"),
    [
        (overview_page, "Overview · Atlas", "Good morning, Lex"),
        (projects_page, "Projects · Atlas", "Projects"),
        (analytics_page, "Analytics · Atlas", "Analytics"),
        (calendar_page, "Calendar · Atlas", "Calendar"),
        (team_page, "Team · Atlas", "Team"),
        (messages_page, "Messages · Atlas", "Messages"),
        (reports_page, "Reports · Atlas", "Reports"),
        (settings_page, "Settings · Atlas", "Settings"),
    ],
)
def test_every_navigation_route_has_independent_ssr_content(renderer, title, heading):
    response = renderer(None)
    header = response.body.children[0]

    assert response.title == title
    assert header.children[1].childNodes[0].data == heading
