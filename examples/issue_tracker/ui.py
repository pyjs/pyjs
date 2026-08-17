from pyjs import js
from pyjs.server import LiveSession, OperationError, WatchedQuery
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, button, h1, input, p, ref, span, tag, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLButtonElement, HTMLElement, HTMLInputElement
from pyjs.web.ui.badge import Badge
from pyjs.web.ui.date import DateText
from pyjs.web.ui.model import ModelForm, TextModelField

from .api import api
from .core import (
    Comment,
    CommentDraft,
    Issue,
    IssueDetail,
    IssueDraft,
    IssueListRequest,
    IssuePage,
    IssueRequest,
    IssueStatusRequest,
    Milestone,
    Project,
)


@js
class IssueForm(ModelForm[IssueDraft]):
    title = TextModelField(label="Title")

    class Meta:
        fields = ("description", "priority")


@js
def default_draft() -> IssueDraft:
    return IssueDraft.model_validate(
        {"description": "", "priority": "normal", "title": ""}
    )


@js
def status_badge(status: str) -> Element:
    if status == "closed":
        return Badge("Closed", variant="secondary")
    return Badge("Open")


@js
def priority_badge(priority: str) -> Element:
    if priority == "high":
        return Badge("High priority", variant="destructive")
    return Badge(priority + " priority", variant="outline")


@js
def issue_card(issue: Issue) -> Element:
    labels: list[Element] = []
    for label in issue.labels:
        labels.append(Badge(label.name, variant="outline"))
    assignee = "Unassigned"
    if issue.assignee is not None:
        assignee = issue.assignee.name
    milestone = "No milestone"
    if issue.milestone is not None:
        milestone = issue.milestone.title
    return tag(
        "article",
        tw(
            "grid gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm "
            "transition hover:border-slate-300 hover:shadow-md"
        ),
        {
            "data-issue-id": str(issue.id),
            "data-status": issue.status,
            "data-testid": "issue-card",
        },
        tag(
            "div",
            tw("flex flex-wrap items-center gap-2"),
            status_badge(issue.status),
            priority_badge(issue.priority),
            *labels,
        ),
        tag(
            "div",
            tag(
                "p",
                tw("text-xs font-medium text-slate-500"),
                issue.project.key + "-" + str(issue.number),
            ),
            tag(
                "h2",
                tw("mt-1 text-base font-semibold text-slate-950"),
                {"data-testid": "issue-title"},
                issue.title,
            ),
            p(tw("mt-1 text-sm leading-6 text-slate-600"), issue.description),
        ),
        tag(
            "div",
            tw("flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500"),
            span("Assigned to " + assignee),
            span("Milestone " + milestone),
            span(str(issue.comment_count) + " comments"),
            span("Updated " + issue.updated_at),
        ),
    )


@js
def comment_card(comment: Comment) -> Element:
    return tag(
        "article",
        tw("grid grid-cols-[2rem_1fr] gap-3 rounded-lg border border-slate-200 p-3"),
        tag(
            "span",
            tw(
                "flex size-8 items-center justify-center rounded-full bg-slate-900 "
                "text-xs font-semibold text-white"
            ),
            comment.author.initials,
        ),
        tag(
            "div",
            tag(
                "div",
                tw("flex items-center justify-between gap-3"),
                tag("strong", tw("text-sm text-slate-900"), comment.author.name),
                span(tw("text-xs text-slate-400"), comment.created_at),
            ),
            p(tw("mt-1 text-sm leading-6 text-slate-600"), comment.body),
        ),
    )


@js
def issue_list_widget() -> HTMLElement:
    return tag("div", tw("grid gap-3"), {"data-testid": "issue-list"})


@js
def issue_detail_widget() -> HTMLElement:
    return tag(
        "aside",
        tw("grid content-start gap-5"),
        {"data-testid": "issue-detail"},
    )


@js
def metric_count(value: int, test_id: str) -> HTMLElement:
    return span(
        tw("text-2xl font-semibold"),
        {"data-testid": test_id},
        str(value),
    )


@js
def issue_count_widget(total: int) -> HTMLElement:
    noun = " issue" if total == 1 else " issues"
    return span(
        tw("text-sm text-slate-500"),
        {"data-testid": "issue-count"},
        str(total) + noun,
    )


@js
def status_widget(test_id: str, initial: str = "") -> HTMLElement:
    return span(
        tw("text-sm text-slate-500"),
        {"aria-live": "polite", "data-testid": test_id},
        initial,
    )


@js
def search_input_widget() -> HTMLInputElement:
    return input(
        tw(
            "h-9 min-w-0 flex-1 rounded-md border border-slate-300 bg-white "
            "px-3 text-sm outline-none focus:ring-2 focus:ring-slate-300"
        ),
        {"aria-label": "Search issues", "placeholder": "Search issues"},
    )


@js
def comment_input_widget() -> HTMLInputElement:
    return input(
        tw(
            "h-9 w-full rounded-md border border-slate-300 bg-white px-3 "
            "text-sm outline-none focus:ring-2 focus:ring-slate-300"
        ),
        {"data-testid": "comment-input", "placeholder": "Add a comment"},
    )


@js
def primary_button(label: str, test_id: str) -> HTMLButtonElement:
    return button(
        tw(
            "h-9 rounded-md bg-slate-950 px-4 text-sm font-medium text-white "
            "hover:bg-slate-800"
        ),
        {"data-testid": test_id, "type": "button"},
        label,
    )


@js
def selected_filter_button() -> HTMLButtonElement:
    return button(
        tw(
            "h-8 rounded-md bg-slate-900 px-3 text-xs font-medium text-white "
            "hover:bg-slate-700"
        ),
        {"data-testid": "filter-all", "type": "button"},
        "All issues",
    )


@js
def filter_button(label: str, test_id: str) -> HTMLButtonElement:
    return button(
        tw(
            "h-8 rounded-md border border-slate-300 bg-white px-3 text-xs "
            "font-medium text-slate-700 hover:bg-slate-100"
        ),
        {"data-testid": test_id, "type": "button"},
        label,
    )


@js
def search_button_widget() -> HTMLButtonElement:
    return button(
        tw(
            "h-9 rounded-md border border-slate-300 bg-white px-3 text-sm "
            "font-medium text-slate-800 hover:bg-slate-100"
        ),
        {"data-testid": "search-issues", "type": "button"},
        "Search",
    )


@js
def close_issue_button() -> HTMLButtonElement:
    return button(
        tw(
            "h-8 rounded-md border border-slate-300 bg-white px-3 text-xs "
            "font-medium text-slate-800 hover:bg-slate-100 disabled:opacity-50"
        ),
        {"data-testid": "close-issue", "type": "button"},
        "Close issue",
    )


@js
def tracker_header(project: Project) -> Element:
    return tag(
        "header",
        tw("border-b border-slate-800 bg-slate-950 text-white"),
        tag(
            "div",
            tw("mx-auto flex max-w-7xl items-center justify-between px-6 py-4"),
            tag(
                "div",
                tag(
                    "p",
                    tw(
                        "text-xs font-semibold uppercase tracking-[0.2em] "
                        "text-cyan-300"
                    ),
                    "Workspace",
                ),
                h1(
                    tw("mt-1 text-xl font-semibold"),
                    {"data-testid": "project-name"},
                    project.name,
                ),
            ),
            Badge("Typed Django API", variant="secondary"),
        ),
    )


@js
def project_summary(project: Project) -> Element:
    return tag(
        "section",
        tw("rounded-xl border border-slate-200 bg-white p-4 shadow-sm"),
        tag(
            "p",
            tw("text-xs font-semibold uppercase tracking-wide text-slate-500"),
            project.key,
        ),
        tag("h2", tw("mt-1 font-semibold text-slate-950"), project.name),
        p(tw("mt-2 text-sm leading-6 text-slate-600"), project.description),
    )


@js
def issue_metrics(open_count: Element, closed_count: Element) -> Element:
    return tag(
        "section",
        tw("grid grid-cols-2 gap-3"),
        tag(
            "div",
            tw("rounded-xl border border-slate-200 bg-white p-4"),
            open_count,
            p(tw("mt-1 text-xs text-slate-500"), "Open"),
        ),
        tag(
            "div",
            tw("rounded-xl border border-slate-200 bg-white p-4"),
            closed_count,
            p(tw("mt-1 text-xs text-slate-500"), "Closed"),
        ),
    )


@js
def new_issue_panel(
    form_widget: IssueForm,
    save_button: Element,
    save_status: Element,
) -> Element:
    return tag(
        "section",
        tw("grid gap-3 rounded-xl border border-slate-200 bg-white p-4"),
        tag("h2", tw("text-sm font-semibold"), "New issue"),
        form_widget,
        tag(
            "div",
            tw("flex flex-wrap items-center gap-3"),
            save_button,
            save_status,
        ),
    )


@js
def project_sidebar(
    project: Project,
    open_count: Element,
    closed_count: Element,
    form_widget: IssueForm,
    save_button: Element,
    save_status: Element,
) -> Element:
    return tag(
        "aside",
        tw("grid content-start gap-5"),
        project_summary(project),
        issue_metrics(open_count, closed_count),
        new_issue_panel(form_widget, save_button, save_status),
    )


@js
def issue_browser(
    issue_count: Element,
    all_filter: Element,
    open_filter: Element,
    closed_filter: Element,
    search_input: Element,
    search_button: Element,
    issue_list: Element,
) -> Element:
    return tag(
        "section",
        tw("grid min-w-0 content-start gap-4"),
        tag(
            "div",
            tw("flex flex-wrap items-center justify-between gap-3"),
            tag("div", tag("h2", tw("text-lg font-semibold"), "Issues"), issue_count),
            tag(
                "div",
                tw("flex flex-wrap gap-2"),
                all_filter,
                open_filter,
                closed_filter,
            ),
        ),
        tag("div", tw("flex gap-2"), search_input, search_button),
        issue_list,
    )


@js
def detail_sidebar(
    detail: Element,
    comment_input: Element,
    comment_status: Element,
    comment_button: Element,
) -> Element:
    return tag(
        "aside",
        tw("min-w-0"),
        tag(
            "div",
            tw(
                "sticky top-6 grid gap-4 rounded-xl border border-slate-200 "
                "bg-white p-5 shadow-sm"
            ),
            detail,
            tag(
                "div",
                tw("grid gap-2 border-t border-slate-200 pt-4"),
                comment_input,
                tag(
                    "div",
                    tw("flex items-center justify-between gap-3"),
                    comment_status,
                    comment_button,
                ),
            ),
        ),
    )


@js
def tracker_layout(sidebar: Element, browser: Element, detail: Element) -> Element:
    return tag(
        "main",
        tw(
            "mx-auto grid max-w-7xl gap-6 px-6 py-6 "
            "lg:grid-cols-[14rem_1fr_22rem]"
        ),
        sidebar,
        browser,
        detail,
    )


@js
class IssueTracker(CustomElement):
    live_session: LiveSession
    issue_query: WatchedQuery[IssuePage]
    detail_query: WatchedQuery[IssueDetail]

    def __init__(self, page: IssuePage, detail: IssueDetail):
        super().__init__()
        self.set_data("filter", "all")
        self.set_data("selected-issue", str(detail.issue.id))
        self.issue_list = ref(issue_list_widget())
        self.detail = ref(issue_detail_widget())
        self.issue_count = ref(issue_count_widget(page.total))
        self.open_count = ref(metric_count(page.open_count, "open-count"))
        self.closed_count = ref(metric_count(page.closed_count, "closed-count"))
        self.form = ref(IssueForm(default_draft()))
        self.form.setAttribute("data-testid", "issue-form")
        self.save_status = ref(status_widget("save-status", "Ready"))
        self.comment_status = ref(status_widget("comment-status"))
        self.search_input = ref(search_input_widget())
        self.comment_input = ref(comment_input_widget())
        self.close_button = ref(close_issue_button())
        self.close_button.addEventListener("click", self.close_issue)
        self.all_filter = ref(selected_filter_button())
        self.all_filter.addEventListener("click", self.show_all)
        self.open_filter = ref(filter_button("Open", "filter-open"))
        self.open_filter.addEventListener("click", self.show_open)
        self.closed_filter = ref(filter_button("Closed", "filter-closed"))
        self.closed_filter.addEventListener("click", self.show_closed)
        self.search_button = ref(search_button_widget())
        self.search_button.addEventListener("click", self.search)
        self.save_button = ref(primary_button("Create issue", "save-issue"))
        self.save_button.addEventListener("click", self.create_issue)
        self.comment_button = ref(primary_button("Comment", "add-comment"))
        self.comment_button.addEventListener("click", self.add_comment)
        sidebar = project_sidebar(
            detail.issue.project,
            self.open_count,
            self.closed_count,
            self.form,
            self.save_button,
            self.save_status,
        )
        browser = issue_browser(
            self.issue_count,
            self.all_filter,
            self.open_filter,
            self.closed_filter,
            self.search_input,
            self.search_button,
            self.issue_list,
        )
        details = detail_sidebar(
            self.detail,
            self.comment_input,
            self.comment_status,
            self.comment_button,
        )
        tag(
            self,
            tracker_header(detail.issue.project),
            tracker_layout(sidebar, browser, details),
        )
        self.set_page(page)
        self.set_detail(detail)

    async def initialize(self):
        self.live_session = LiveSession()
        self.issue_query = (
            WatchedQuery[IssuePage](api.issues.list, self.issue_request())
            .on_update(self.set_page)
            .watch(self.live_session, "issues")
        )
        self.detail_query = (
            WatchedQuery[IssueDetail](api.issues.get, self.detail_request())
            .on_update(self.set_detail)
            .watch(self.live_session, "issues")
        )
        projects = await api.projects.list()
        if projects:
            project = projects[0]
            self.set_data("project-api", project.key)
            milestones = api.projects.related(
                str(project.id),
                api.projects.milestones,
            )
            if isinstance(milestones, list):
                if len(milestones) > 0:
                    milestone = milestones[0]
                    if isinstance(milestone, Milestone):
                        self.set_data("milestone-api", milestone.title)

    def set_page(self, page: IssuePage):
        cards: list[Element] = []
        for issue in page.items:
            cards.append(issue_card(issue))
        if not cards:
            cards.append(
                tag(
                    "p",
                    tw(
                        "rounded-xl border border-dashed border-slate-300 "
                        "bg-white p-8 text-center text-sm text-slate-500"
                    ),
                    "No issues match this view.",
                )
            )
        self.issue_list.replaceChildren(*cards)
        noun = " issue" if page.total == 1 else " issues"
        self.issue_count.textContent = str(page.total) + noun
        self.open_count.textContent = str(page.open_count)
        self.closed_count.textContent = str(page.closed_count)

    def set_detail(self, detail: IssueDetail):
        issue = detail.issue
        self.set_data("selected-issue", str(issue.id))
        labels: list[Element] = []
        for label in issue.labels:
            labels.append(Badge(label.name, variant="outline"))
        comments: list[Element] = []
        for comment in detail.comments:
            comments.append(comment_card(comment))
        activity: list[Element] = []
        for event in detail.activity:
            activity.append(
                tag(
                    "li",
                    tw("text-xs leading-5 text-slate-500"),
                    tag("strong", tw("text-slate-700"), event.actor.name),
                    " " + event.message + " · " + event.occurred_at,
                )
            )
        milestone: Element = span("No milestone")
        if issue.milestone is not None:
            milestone = tag(
                "span",
                issue.milestone.title + " · ",
                DateText(issue.milestone.due_date),
            )
        assignee = "Unassigned"
        if issue.assignee is not None:
            assignee = issue.assignee.name
        comment_label = " comment" if len(comments) == 1 else " comments"
        self.detail.replaceChildren(
            tag(
                "div",
                tw("flex flex-wrap items-center gap-2"),
                status_badge(issue.status),
                priority_badge(issue.priority),
                *labels,
            ),
            tag(
                "div",
                p(
                    tw("text-xs font-medium text-slate-500"),
                    issue.project.key + "-" + str(issue.number),
                ),
                tag(
                    "h2",
                    tw("mt-1 text-lg font-semibold text-slate-950"),
                    {"data-testid": "detail-title"},
                    issue.title,
                ),
                p(tw("mt-2 text-sm leading-6 text-slate-600"), issue.description),
            ),
            tag(
                "dl",
                tw("grid grid-cols-2 gap-3 text-xs"),
                tag(
                    "div",
                    tag("dt", tw("text-slate-400"), "Assignee"),
                    tag("dd", assignee),
                ),
                tag(
                    "div",
                    tag("dt", tw("text-slate-400"), "Milestone"),
                    tag("dd", milestone),
                ),
            ),
            tag(
                "div",
                tw(
                    "flex items-center justify-between border-y "
                    "border-slate-200 py-3"
                ),
                span(
                    tw("text-xs text-slate-500"),
                    {"data-testid": "comment-count"},
                    str(len(comments)) + comment_label,
                ),
                self.close_button,
            ),
            tag("div", tw("grid gap-3"), *comments),
            tag(
                "div",
                tag(
                    "h3",
                    tw(
                        "text-xs font-semibold uppercase tracking-wide "
                        "text-slate-500"
                    ),
                    "Activity",
                ),
                tag("ul", tw("mt-2 grid gap-2"), *activity),
            ),
        )
        self.close_button.disabled = issue.status == "closed"

    def issue_request(self) -> IssueListRequest:
        current_filter = self.get_data("filter") or "all"
        return IssueListRequest.model_validate(
            {
                "query": self.search_input.value,
                "status": current_filter,
            }
        )

    def detail_request(self) -> IssueRequest:
        selected = self.get_data("selected-issue")
        if selected is None:
            raise ValueError("The issue tracker has no selected issue.")
        return IssueRequest.model_validate({"issue_id": int(selected)})

    async def load_issues(self, status: str, search: str = ""):
        self.set_data("filter", status)
        self.search_input.value = search
        await self.issue_query.set_args(self.issue_request()).reload()

    async def load_detail(self, issue_id: int):
        self.set_data("selected-issue", str(issue_id))
        await self.detail_query.set_args(self.detail_request()).reload()

    async def show_all(self, event: Event):
        await self.load_issues("all")

    async def show_open(self, event: Event):
        await self.load_issues("open")

    async def show_closed(self, event: Event):
        await self.load_issues("closed")

    async def search(self, event: Event):
        current_filter = self.get_data("filter")
        if current_filter is None:
            current_filter = "all"
        await self.load_issues(current_filter, self.search_input.value)

    async def create_issue(self, event: Event):
        event.preventDefault()
        self.save_status.textContent = "Creating…"
        draft = IssueDraft.model_validate(self.form.values())
        try:
            result = await api.issues.save(draft)
        except Exception as error:
            if not isinstance(error, OperationError):
                raise error
            self.form.set_errors(error.issues, "draft")
            self.save_status.textContent = "Correct the highlighted fields"
            return
        issue = result.issue
        self.form.clear_errors()
        self.form.set_model(default_draft())
        await self.load_issues("all")
        await self.load_detail(issue.id)
        self.save_status.textContent = (
            "Created " + issue.project.key + "-" + str(issue.number)
        )

    async def add_comment(self, event: Event):
        event.preventDefault()
        selected = self.get_data("selected-issue")
        if selected is None:
            return
        if not self.comment_input.value.strip():
            self.comment_status.textContent = "Enter a comment"
            return
        issue_id = int(selected)
        await api.issues.comments.add(
            CommentDraft.model_validate(
                {"body": self.comment_input.value, "issue_id": issue_id}
            )
        )
        self.comment_input.value = ""
        await self.load_detail(issue_id)
        self.comment_status.textContent = "Comment added"

    async def close_issue(self, event: Event):
        event.preventDefault()
        selected = self.get_data("selected-issue")
        if selected is None:
            return
        issue_id = int(selected)
        await api.issues.set_status(
            IssueStatusRequest.model_validate(
                {"issue_id": issue_id, "status": "closed"}
            )
        )
        await self.load_issues("all")
        await self.load_detail(issue_id)


@js
def main():
    return IssueTracker
