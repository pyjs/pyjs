import os

from pyjs.server import serve
from pyjs_examples.navigation.navigation import (
    analytics_page,
    analytics_view,
    calendar_page,
    calendar_view,
    layout,
    messages_page,
    messages_view,
    overview_page,
    overview_view,
    projects_page,
    projects_view,
    reports_page,
    reports_view,
    settings_page,
    settings_view,
    team_page,
    team_view,
)

serve(
    "pyjs_examples.navigation.navigation",
    routes={
        ("GET", "/"): overview_page,
        ("GET", "/analytics"): analytics_page,
        ("GET", "/calendar"): calendar_page,
        ("GET", "/messages"): messages_page,
        ("GET", "/projects"): projects_page,
        ("GET", "/reports"): reports_page,
        ("GET", "/settings"): settings_page,
        ("GET", "/team"): team_page,
    },
    layout=layout,
    layout_id="atlas",
    page_entry_points=(
        overview_view,
        analytics_view,
        calendar_view,
        messages_view,
        projects_view,
        reports_view,
        settings_view,
        team_view,
    ),
    port=int(os.environ.get("PYJS_PORT", "8000")),
)
