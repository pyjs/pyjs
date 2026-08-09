from pyjs import js, nojs
from pyjs.server import NavigationPage
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, a, button, h1, h2, p, ref, span, tag, tw
from pyjs.web.events import Event
from pyjs.web.navigation import NavigationLayout


@js
def icon(value: str):
    return span(
        tw("flex h-8 w-8 items-center justify-center rounded-lg bg-slate-800 text-sm"),
        {"aria-hidden": "true"},
        value,
    )


@js
def navigation_link(path: str, label: str, symbol: str):
    return a(
        tw(
            "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium "
            "text-slate-400 transition hover:bg-slate-800 hover:text-white "
            "aria-[current=page]:bg-indigo-500/15 aria-[current=page]:text-indigo-300"
        ),
        {
            "data-navigation-link": label.lower(),
            "data-pyjs-navigation-link": "",
            "href": path,
        },
        icon(symbol),
        span(label),
    )


@js
def application_navigation(mobile: bool):
    if mobile:
        attributes = tw(
            "flex gap-1 overflow-x-auto border-b border-slate-200 bg-white px-4 py-2 "
            "lg:hidden"
        )
        attributes["aria-label"] = "Mobile application"
        attributes["data-mobile-navigation"] = ""
    else:
        attributes = tw("flex flex-1 flex-col gap-1")
        attributes["aria-label"] = "Application"
    return tag(
        "nav",
        attributes,
        navigation_link("/", "Overview", "⌂"),
        navigation_link("/projects", "Projects", "◆"),
        navigation_link("/analytics", "Analytics", "↗"),
        navigation_link("/calendar", "Calendar", "□"),
        navigation_link("/team", "Team", "◎"),
        navigation_link("/messages", "Messages", "✦"),
        navigation_link("/reports", "Reports", "≡"),
        navigation_link("/settings", "Settings", "⚙"),
    )


@js
def page_header(kicker: str, title: str, description: str):
    return tag(
        "header",
        tw("mb-8 flex flex-col gap-2"),
        p(
            tw("text-xs font-semibold uppercase tracking-[0.22em] text-indigo-500"),
            kicker,
        ),
        h1(tw("text-3xl font-semibold tracking-tight text-slate-950"), title),
        p(tw("max-w-2xl text-sm leading-6 text-slate-500"), description),
    )


@js
def page_body(*children):
    return tag(
        "main",
        tw("mx-auto w-full max-w-7xl px-5 py-8 sm:px-8 lg:px-10"),
        {"data-page-content": ""},
        *children,
    )


@js
def card(*children):
    return tag(
        "section",
        tw("rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"),
        *children,
    )


@js
def metric(label: str, value: str, detail: str):
    return card(
        div_label(label),
        p(tw("mt-3 text-3xl font-semibold tracking-tight text-slate-950"), value),
        p(tw("mt-2 text-xs font-medium text-emerald-600"), detail),
    )


@js
def div_label(label: str):
    return p(tw("text-sm font-medium text-slate-500"), label)


@js
def section_heading(title: str, detail: str):
    return tag(
        "div",
        tw("mb-5 flex items-end justify-between gap-4"),
        tag(
            "div",
            h2(tw("text-lg font-semibold text-slate-950"), title),
            p(tw("mt-1 text-sm text-slate-500"), detail),
        ),
        a(
            tw("text-sm font-medium text-indigo-600 hover:text-indigo-800"),
            {"href": "/reports"},
            "View report",
        ),
    )


@js
def status(value: str):
    return span(
        tw(
            "inline-flex rounded-full bg-indigo-50 px-2.5 py-1 text-xs "
            "font-semibold text-indigo-700"
        ),
        value,
    )


@js
def activity_row(symbol: str, title: str, detail: str, time: str):
    return tag(
        "li",
        tw("flex items-start gap-4 border-b border-slate-100 py-4 last:border-0"),
        icon(symbol),
        tag(
            "div",
            tw("min-w-0 flex-1"),
            p(tw("font-medium text-slate-900"), title),
            p(tw("mt-1 text-sm text-slate-500"), detail),
        ),
        span(tw("whitespace-nowrap text-xs text-slate-400"), time),
    )


@js
class PreferencesPanel(CustomElement):
    def __init__(self):
        super().__init__()
        self.set_data("digest", "enabled")
        self.state = ref(
            span(
                tw("text-sm font-semibold text-emerald-600"),
                {"data-preference-state": ""},
                "Enabled",
            )
        )
        self.toggle = ref(
            button(
                tw(
                    "rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white "
                    "hover:bg-slate-800 focus:outline-none focus:ring-2 "
                    "focus:ring-indigo-500"
                ),
                {"data-preference-toggle": "", "type": "button"},
                "Toggle digest",
            )
        )
        tag(
            self,
            tw("block rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"),
            tag(
                "div",
                tw("flex items-center justify-between gap-5"),
                tag(
                    "div",
                    h2(tw("font-semibold text-slate-950"), "Weekly project digest"),
                    p(
                        tw("mt-1 text-sm text-slate-500"),
                        "Receive a concise Monday summary of project movement.",
                    ),
                ),
                self.state,
            ),
            tag("div", tw("mt-5"), self.toggle),
        )
        self.toggle.addEventListener("click", self.toggle_digest)

    def toggle_digest(self, event: Event):
        enabled = self.get_data("digest") == "enabled"
        if enabled:
            self.set_data("digest", "disabled")
            self.state.textContent = "Disabled"
            tag(self.state, tw("text-sm font-semibold text-slate-500"))
        else:
            self.set_data("digest", "enabled")
            self.state.textContent = "Enabled"
            tag(self.state, tw("text-sm font-semibold text-emerald-600"))


@js
class AtlasLayout(NavigationLayout):
    def __init__(self, content: Element, layout_id: str = "atlas"):
        super().__init__(content, layout_id)
        self.set_data("navigation-count", "0")
        self.sidebar = ref(
            tag(
                "aside",
                tw(
                    "fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r "
                    "border-slate-800 bg-slate-950 px-4 py-5 text-white lg:flex"
                ),
                {"data-navigation-sidebar": ""},
                a(
                    tw("mb-7 flex items-center gap-3 px-2"),
                    {"href": "/"},
                    span(
                        tw(
                            "flex h-10 w-10 items-center justify-center rounded-xl "
                            "bg-indigo-500 font-bold shadow-lg shadow-indigo-500/30"
                        ),
                        "A",
                    ),
                    tag(
                        "div",
                        p(tw("font-semibold tracking-tight"), "Atlas"),
                        p(tw("text-xs text-slate-500"), "Operations workspace"),
                    ),
                ),
                application_navigation(False),
                tag(
                    "div",
                    tw("rounded-xl border border-slate-800 bg-slate-900 p-3"),
                    p(tw("text-xs font-medium text-slate-400"), "Persistent shell"),
                    p(
                        tw("mt-1 text-sm text-slate-200"),
                        "Completed navigations: ",
                        self.navigation_count(),
                    ),
                ),
            )
        )
        self.add(
            tw("block min-h-screen bg-slate-50 text-slate-900"),
            self.sidebar,
            tag(
                "div",
                tw("min-h-screen lg:pl-64"),
                tag(
                    "header",
                    tw(
                        "sticky top-0 z-10 flex h-16 items-center justify-between "
                        "border-b border-slate-200 bg-white/90 px-5 backdrop-blur sm:px-8"
                    ),
                    tag(
                        "div",
                        p(
                            tw("text-sm font-semibold text-slate-900"),
                            "Northstar program",
                        ),
                        p(tw("text-xs text-slate-500"), "Last synchronized moments ago"),
                    ),
                    tag(
                        "div",
                        tw("flex items-center gap-3"),
                        span(
                            tw(
                                "hidden rounded-full bg-emerald-50 px-3 py-1 text-xs "
                                "font-semibold text-emerald-700 sm:inline-flex"
                            ),
                            "All systems operational",
                        ),
                        span(
                            tw(
                                "flex h-9 w-9 items-center justify-center rounded-full "
                                "bg-indigo-100 text-sm font-semibold text-indigo-700"
                            ),
                            "LB",
                        ),
                    ),
                ),
                application_navigation(True),
                self.outlet,
            ),
        )
        self.addEventListener("pyjs:navigation-end", self.navigation_completed)

    def navigation_count(self):
        return span(
            {"data-navigation-count-label": ""},
            self.get_data("navigation-count") or "0",
        )

    def navigation_completed(self, event: Event):
        value = self.get_data("navigation-count")
        count = int(value) + 1 if value is not None else 1
        self.set_data("navigation-count", str(count))
        label = self.querySelector("[data-navigation-count-label]")
        if label is not None:
            label.textContent = str(count)


@js
def overview_view():
    return page_body(
        page_header(
            "Workspace overview",
            "Good morning, Lex",
            "A concise view of the work, people, and signals moving the program forward.",
        ),
        tag(
            "div",
            tw("grid gap-4 sm:grid-cols-2 xl:grid-cols-4"),
            metric("Active projects", "12", "+2 this month"),
            metric("Team capacity", "84%", "6 points available"),
            metric("Open decisions", "7", "3 need attention"),
            metric("On-time delivery", "96%", "+4.2% this quarter"),
        ),
        tag(
            "div",
            tw("mt-6 grid gap-6 xl:grid-cols-[1.35fr_0.65fr]"),
            card(
                section_heading(
                    "Recent activity",
                    "Updates across your active workstreams.",
                ),
                tag(
                    "ul",
                    activity_row(
                        "✓",
                        "Launch plan approved",
                        "Maya closed the review round.",
                        "12 min",
                    ),
                    activity_row(
                        "↗",
                        "Preview deployed",
                        "Noah published build 842 to staging.",
                        "43 min",
                    ),
                    activity_row(
                        "◎",
                        "Research shared",
                        "Inez added eight customer interviews.",
                        "2 hr",
                    ),
                    activity_row(
                        "◆",
                        "Milestone reached",
                        "The billing migration is at 75%.",
                        "4 hr",
                    ),
                ),
            ),
            card(
                h2(tw("text-lg font-semibold text-slate-950"), "This week"),
                p(tw("mt-1 text-sm text-slate-500"), "Capacity by discipline"),
                tag(
                    "div",
                    tw("mt-6 flex h-48 items-end gap-3"),
                    chart_bar("Design", "72%", "72%"),
                    chart_bar("Web", "91%", "91%"),
                    chart_bar("API", "83%", "83%"),
                    chart_bar("QA", "64%", "64%"),
                ),
            ),
        ),
    )


@js
def chart_bar(label: str, value: str, height: str):
    return tag(
        "div",
        tw("flex h-full flex-1 flex-col justify-end gap-2 text-center"),
        span(tw("text-xs font-semibold text-slate-500"), value),
        span(
            tw("w-full rounded-t-lg bg-indigo-500"),
            {"aria-label": label + " " + value, "style": "height: " + height},
        ),
        span(tw("text-xs text-slate-500"), label),
    )


@js
def projects_view():
    return page_body(
        page_header(
            "Delivery",
            "Projects",
            "Track outcomes, owners, and the next meaningful milestone for every "
            "initiative.",
        ),
        tag(
            "div",
            tw("grid gap-5 lg:grid-cols-2 2xl:grid-cols-3"),
            project_card("Northstar launch", "Product", "Maya Chen", "Sep 18", "78%"),
            project_card(
                "Billing migration", "Platform", "Noah Williams", "Oct 02", "64%"
            ),
            project_card(
                "Mobile foundations", "Engineering", "Ari Singh", "Oct 21", "42%"
            ),
            project_card("Customer council", "Research", "Inez Taylor", "Nov 04", "31%"),
            project_card("Design system v2", "Design", "Leah Brooks", "Nov 15", "55%"),
            project_card(
                "Growth experiments", "Marketing", "Sam Rivera", "Dec 01", "24%"
            ),
        ),
    )


@js
def project_card(title: str, group: str, owner: str, due: str, progress: str):
    return card(
        tag(
            "div",
            tw("flex items-start justify-between gap-4"),
            tag(
                "div",
                status(group),
                h2(tw("mt-4 text-lg font-semibold text-slate-950"), title),
            ),
            button(
                tw("rounded-lg px-2 text-xl text-slate-400 hover:bg-slate-100"),
                {"aria-label": "Project actions", "type": "button"},
                "⋯",
            ),
        ),
        tag(
            "div",
            tw("mt-6 flex justify-between text-sm text-slate-500"),
            span(owner),
            span("Due " + due),
        ),
        tag(
            "div",
            tw("mt-4 h-2 overflow-hidden rounded-full bg-slate-100"),
            span(
                tw("block h-full rounded-full bg-indigo-500"),
                {"style": "width: " + progress},
            ),
        ),
        p(tw("mt-2 text-right text-xs font-semibold text-slate-500"), progress),
    )


@js
def analytics_view():
    return page_body(
        page_header(
            "Signals",
            "Analytics",
            "Understand delivery velocity and where the team is gaining or losing "
            "momentum.",
        ),
        tag(
            "div",
            tw("grid gap-4 sm:grid-cols-3"),
            metric("Cycle time", "3.8d", "0.6d faster"),
            metric("Throughput", "47", "+12% vs last month"),
            metric("Work in progress", "19", "Within target range"),
        ),
        card(
            tw("mt-6"),
            section_heading(
                "Delivery velocity",
                "Completed work over the last eight weeks.",
            ),
            tag(
                "div",
                tw("flex h-72 items-end gap-3 rounded-xl bg-slate-50 p-5"),
                chart_bar("W1", "58", "58%"),
                chart_bar("W2", "66", "66%"),
                chart_bar("W3", "51", "51%"),
                chart_bar("W4", "74", "74%"),
                chart_bar("W5", "69", "69%"),
                chart_bar("W6", "82", "82%"),
                chart_bar("W7", "76", "76%"),
                chart_bar("W8", "91", "91%"),
            ),
        ),
    )


@js
def calendar_view():
    return page_body(
        page_header(
            "Planning",
            "Calendar",
            "Keep milestones, reviews, and team rituals visible in one shared schedule.",
        ),
        card(
            tag(
                "div",
                tw("mb-6 flex items-center justify-between"),
                h2(tw("text-lg font-semibold text-slate-950"), "August 3–7"),
                tag(
                    "div",
                    tw("flex gap-2"),
                    button(tw("rounded-lg border px-3 py-1.5 text-sm"), "Previous"),
                    button(tw("rounded-lg border px-3 py-1.5 text-sm"), "Next"),
                ),
            ),
            tag(
                "div",
                tw(
                    "grid min-w-[720px] grid-cols-5 gap-px overflow-hidden rounded-xl "
                    "bg-slate-200"
                ),
                calendar_day("Mon 3", "Launch readiness", "10:00"),
                calendar_day("Tue 4", "Design critique", "13:30"),
                calendar_day("Wed 5", "Customer council", "09:00"),
                calendar_day("Thu 6", "No meetings", "Focus day"),
                calendar_day("Fri 7", "Weekly review", "15:00"),
            ),
        ),
    )


@js
def calendar_day(day: str, event: str, time: str):
    return tag(
        "section",
        tw("min-h-72 bg-white p-4"),
        p(tw("text-xs font-semibold uppercase tracking-wide text-slate-400"), day),
        tag(
            "div",
            tw("mt-8 rounded-xl bg-indigo-50 p-3 text-indigo-800"),
            p(tw("font-semibold"), event),
            p(tw("mt-1 text-xs opacity-70"), time),
        ),
    )


@js
def team_view():
    return page_body(
        page_header(
            "People",
            "Team",
            "See who is contributing, what they own, and where collaboration is "
            "happening.",
        ),
        tag(
            "div",
            tw("grid gap-4 sm:grid-cols-2 xl:grid-cols-3"),
            person("MC", "Maya Chen", "Product lead", "New York", "Available"),
            person("NW", "Noah Williams", "Platform engineer", "London", "In focus time"),
            person("IT", "Inez Taylor", "Research lead", "Toronto", "Available"),
            person("AS", "Ari Singh", "Mobile engineer", "Austin", "In a meeting"),
            person("LB", "Leah Brooks", "Product designer", "Berlin", "Available"),
            person("SR", "Sam Rivera", "Growth lead", "Lisbon", "Offline"),
        ),
    )


@js
def person(initials: str, name: str, role: str, city: str, presence: str):
    return card(
        tag(
            "div",
            tw("flex items-center gap-4"),
            span(
                tw(
                    "flex h-12 w-12 items-center justify-center rounded-full "
                    "bg-indigo-100 font-semibold text-indigo-700"
                ),
                initials,
            ),
            tag(
                "div",
                h2(tw("font-semibold text-slate-950"), name),
                p(tw("text-sm text-slate-500"), role),
            ),
        ),
        tag(
            "div",
            tw("mt-5 flex items-center justify-between border-t pt-4 text-xs"),
            span(tw("text-slate-500"), city),
            status(presence),
        ),
    )


@js
def messages_view():
    return page_body(
        page_header(
            "Collaboration",
            "Messages",
            "Follow the conversations that need your input without losing the "
            "surrounding work.",
        ),
        card(
            message(
                "MC",
                "Maya Chen",
                "Launch readiness",
                "Can you review the final rollout?",
                "4m",
            ),
            message(
                "NW", "Noah Williams", "Platform", "The staging deploy is ready.", "28m"
            ),
            message(
                "IT",
                "Inez Taylor",
                "Customer council",
                "I added the interview themes.",
                "1h",
            ),
            message(
                "LB",
                "Leah Brooks",
                "Design system",
                "New navigation states are attached.",
                "3h",
            ),
            message(
                "SR",
                "Sam Rivera",
                "Growth",
                "The experiment brief is ready.",
                "Yesterday",
            ),
        ),
    )


@js
def message(initials: str, name: str, subject: str, preview: str, time: str):
    return tag(
        "article",
        tw("flex items-center gap-4 border-b border-slate-100 py-4 last:border-0"),
        span(
            tw(
                "flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 "
                "text-xs font-semibold text-slate-700"
            ),
            initials,
        ),
        tag(
            "div",
            tw("min-w-0 flex-1"),
            tag(
                "div",
                tw("flex items-center gap-2"),
                h2(tw("font-semibold text-slate-950"), name),
                span(tw("text-xs text-slate-400"), "in " + subject),
            ),
            p(tw("mt-1 truncate text-sm text-slate-500"), preview),
        ),
        span(tw("text-xs text-slate-400"), time),
    )


@js
def reports_view():
    return page_body(
        page_header(
            "Knowledge",
            "Reports",
            "Reusable summaries for leadership, planning, and the teams doing the work.",
        ),
        tag(
            "div",
            tw("grid gap-5 md:grid-cols-2"),
            report("Quarterly delivery review", "Updated today", "12 pages", "Executive"),
            report(
                "Customer insight digest", "Updated yesterday", "24 insights", "Research"
            ),
            report(
                "Platform reliability", "Updated Aug 4", "99.97% uptime", "Engineering"
            ),
            report("Team capacity plan", "Updated Aug 1", "6 disciplines", "Operations"),
        ),
    )


@js
def report(title: str, updated: str, detail: str, group: str):
    return card(
        tag(
            "div",
            tw("flex items-start justify-between"),
            icon("▤"),
            status(group),
        ),
        h2(tw("mt-5 text-lg font-semibold text-slate-950"), title),
        p(tw("mt-2 text-sm text-slate-500"), updated + " · " + detail),
        button(
            tw(
                "mt-5 rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold "
                "text-slate-700 hover:bg-slate-50"
            ),
            {"type": "button"},
            "Open report",
        ),
    )


@js
def settings_view():
    return page_body(
        page_header(
            "Configuration",
            "Settings",
            "Tune workspace behavior. This panel is hydrated after partial navigation.",
        ),
        tag(
            "div",
            tw("grid gap-6 xl:grid-cols-[1fr_0.7fr]"),
            PreferencesPanel(),
            card(
                h2(tw("font-semibold text-slate-950"), "Workspace details"),
                p(tw("mt-2 text-sm text-slate-500"), "Northstar program"),
                tag(
                    "dl",
                    tw("mt-5 space-y-3 text-sm"),
                    detail_row("Region", "United States"),
                    detail_row("Time zone", "America/New_York"),
                    detail_row("Default view", "Overview"),
                ),
            ),
        ),
    )


@js
def detail_row(label: str, value: str):
    return tag(
        "div",
        tw("flex justify-between gap-5 border-b border-slate-100 pb-3 last:border-0"),
        tag("dt", tw("text-slate-500"), label),
        tag("dd", tw("font-medium text-slate-900"), value),
    )


@nojs
def layout(request, content: Element, layout_id: str):
    return AtlasLayout(content, layout_id)


@nojs
def navigation_response(content: Element, title: str):
    return NavigationPage(content, title + " · Atlas")


@nojs
def overview_page(request):
    return navigation_response(overview_view(), "Overview")


@nojs
def projects_page(request):
    return navigation_response(projects_view(), "Projects")


@nojs
def analytics_page(request):
    return navigation_response(analytics_view(), "Analytics")


@nojs
def calendar_page(request):
    return navigation_response(calendar_view(), "Calendar")


@nojs
def team_page(request):
    return navigation_response(team_view(), "Team")


@nojs
def messages_page(request):
    return navigation_response(messages_view(), "Messages")


@nojs
def reports_page(request):
    return navigation_response(reports_view(), "Reports")


@nojs
def settings_page(request):
    return navigation_response(settings_view(), "Settings")


def main():
    return AtlasLayout(overview_view())
