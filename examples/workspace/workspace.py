from pyjs import effect, js, state
from pyjs.web.domx import div, h1, h3, p, ref, span, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget
from pyjs.web.ui.accordion import AccordionGroup, AccordionItem
from pyjs.web.ui.alert import Alert, AlertDescription, AlertTitle
from pyjs.web.ui.attachment import (
    Attachment,
    AttachmentAction,
    AttachmentActions,
    AttachmentContent,
    AttachmentDescription,
    AttachmentMedia,
    AttachmentTitle,
)
from pyjs.web.ui.avatar import Avatar, AvatarBadge, AvatarGroup
from pyjs.web.ui.badge import Badge
from pyjs.web.ui.breadcrumb import (
    Breadcrumb,
    BreadcrumbItem,
    BreadcrumbLink,
    BreadcrumbList,
    BreadcrumbPage,
    BreadcrumbSeparator,
)
from pyjs.web.ui.bubble import Bubble, BubbleContent, BubbleReactions
from pyjs.web.ui.button import Button
from pyjs.web.ui.calendar import Calendar
from pyjs.web.ui.card import Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle
from pyjs.web.ui.carousel import Carousel, CarouselItem
from pyjs.web.ui.chart import BarChart
from pyjs.web.ui.checkbox import Checkbox
from pyjs.web.ui.collapsible import Collapsible, CollapsibleContent, CollapsibleTrigger
from pyjs.web.ui.context_menu import (
    ContextMenu,
    ContextMenuContent,
    ContextMenuItem,
    ContextMenuLabel,
    ContextMenuSeparator,
    ContextMenuTrigger,
)
from pyjs.web.ui.date_picker import DatePicker
from pyjs.web.ui.dialog import (
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
)
from pyjs.web.ui.dropdown_menu import (
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
)
from pyjs.web.ui.hover_card import HoverCard, HoverCardContent, HoverCardTrigger
from pyjs.web.ui.input import Input
from pyjs.web.ui.item import Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle
from pyjs.web.ui.kbd import Kbd, KbdGroup
from pyjs.web.ui.label import Label
from pyjs.web.ui.marker import Marker, MarkerContent, MarkerIcon
from pyjs.web.ui.message import Message, MessageAvatar, MessageContent, MessageGroup, MessageHeader
from pyjs.web.ui.pagination import (
    Pagination,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationLink,
    PaginationNext,
    PaginationPrevious,
)
from pyjs.web.ui.progress import ProgressBar
from pyjs.web.ui.radio_group import RadioGroup, RadioGroupItem
from pyjs.web.ui.scroll_area import ScrollArea
from pyjs.web.ui.select import Select, SelectContent, SelectItem, SelectTrigger
from pyjs.web.ui.separator import Separator
from pyjs.web.ui.sheet import (
    Sheet,
    SheetClose,
    SheetContent,
    SheetDescription,
    SheetFooter,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
)
from pyjs.web.ui.sidebar import (
    Sidebar,
    SidebarContent,
    SidebarFooter,
    SidebarGroup,
    SidebarGroupContent,
    SidebarGroupLabel,
    SidebarHeader,
    SidebarInset,
    SidebarLayout,
    SidebarMenu,
    SidebarMenuBadge,
    SidebarMenuButton,
    SidebarMenuItem,
    SidebarSeparator,
    SidebarTrigger,
)
from pyjs.web.ui.slider import Slider
from pyjs.web.ui.sonner import Toaster
from pyjs.web.ui.switch import Switch
from pyjs.web.ui.table import Table, TableBody, TableCell, TableHead, TableHeader, TableRow
from pyjs.web.ui.tabs import Tab, TabGroup
from pyjs.web.ui.textarea import Textarea
from pyjs.web.ui.toggle import Toggle, ToggleGroup
from pyjs.web.ui.tooltip import Tooltip, TooltipContent, TooltipTrigger


@js
def form_field(label: str, control: object, hint: str = ""):
    field = div(tw("grid gap-2"), Label(label), control)
    if hint != "":
        field.append(p(tw("text-xs text-slate-500"), hint))
    return field


@js
def metric_card(label: str, value: str, change: str, detail: str):
    return Card(
        CardHeader(
            CardDescription(label),
            CardTitle(span(tw("text-3xl font-semibold tracking-tight"), value)),
            CardAction(Badge(change, variant="secondary")),
        ),
        CardContent(p(tw("text-xs text-slate-500"), detail)),
    )


@js
def task_row(task_id: str, title: str, owner: str, status: str, priority: str):
    status_variant = "secondary"
    if status == "Blocked":
        status_variant = "destructive"
    elif status == "In review":
        status_variant = "outline"
    menu_button = tag(
        "button",
        tw("rounded px-2 py-1 text-slate-500 hover:bg-slate-100"),
        {
            "aria-label": "Actions for " + task_id,
            "data-testid": "task-menu-" + task_id,
            "type": "button",
        },
        "•••",
    )
    row_menu = ContextMenu(
        ContextMenuTrigger(menu_button),
        ContextMenuContent(
            ContextMenuLabel(task_id),
            ContextMenuSeparator(),
            ContextMenuItem("open", "Open task"),
            ContextMenuItem("duplicate", "Duplicate"),
            ContextMenuItem("archive", "Archive"),
        ),
    )
    return TableRow(
        TableCell(Checkbox(name="task-" + task_id)),
        TableCell(span(tw("font-mono text-xs text-slate-500"), task_id)),
        TableCell(span(tw("font-medium text-slate-950"), title)),
        TableCell(owner),
        TableCell(Badge(status, variant=status_variant)),
        TableCell(Marker(MarkerIcon("◆"), MarkerContent(priority), variant="outline")),
        TableCell(row_menu),
    )


@js
def milestone(title: str, description: str, status: str):
    return CarouselItem(
        div(
            tw("mx-14 grid min-h-40 content-center gap-3 rounded-lg bg-slate-950 p-6 text-white"),
            Badge(status, variant="secondary"),
            h3(tw("text-xl font-semibold"), title),
            p(tw("max-w-lg text-sm text-slate-300"), description),
        )
    )


@js
class WorkspaceApp(Widget):
    task_count = state(5)

    def __init__(self):
        super().__init__()

        self.toaster = ref(Toaster())
        self.task_title = ref(Input(placeholder="What needs to be done?", name="title"))
        self.task_title.setAttribute("data-testid", "task-title")
        self.task_description = ref(
            Textarea(placeholder="Add context, acceptance criteria, or links.", name="description")
        )
        self.task_priority = ref(
            Select(
                SelectTrigger("Choose priority"),
                SelectContent(
                    SelectItem("low", "Low"),
                    SelectItem("medium", "Medium"),
                    SelectItem("high", "High"),
                ),
                value="medium",
            )
        )
        self.task_type = ref(
            RadioGroup(
                RadioGroupItem("feature", "Feature", checked=True),
                RadioGroupItem("bug", "Bug"),
                RadioGroupItem("content", "Content"),
                name="task-type",
                orientation="horizontal",
            )
        )
        self.due_date = ref(
            DatePicker(
                Calendar(
                    "July",
                    2026,
                    days=31,
                    starts_on=3,
                    selected_day=28,
                    disabled_days=[4, 5, 11, 12, 18, 19, 25, 26],
                ),
                placeholder="Choose due date",
            )
        )
        self.create_task_button = ref(Button("Create task"))
        self.create_task_button.setAttribute("data-testid", "create-task")
        self.create_task_button.on_click(self.create_task)
        self.new_task_dialog = ref(
            Dialog(
                DialogTrigger("＋ New task"),
                DialogContent(
                    "Create a task",
                    DialogHeader(
                        DialogTitle("Create a task"),
                        DialogDescription(
                            "Add work to the launch plan. The team will be notified immediately."
                        ),
                    ),
                    div(
                        tw("grid gap-4"),
                        form_field("Title", self.task_title, "Keep it short and action oriented."),
                        form_field("Description", self.task_description),
                        div(
                            tw("grid gap-4 sm:grid-cols-2"),
                            form_field("Priority", self.task_priority),
                            form_field("Due date", self.due_date),
                        ),
                        form_field("Work type", self.task_type),
                    ),
                    DialogFooter(DialogClose("Cancel"), self.create_task_button),
                ),
            )
        )
        self.new_task_dialog.trigger.setAttribute("data-testid", "new-task-trigger")

        self.notification_switch = ref(Switch(name="notifications", checked=True))
        self.capacity_slider = ref(
            Slider(value=72, minimum=20, maximum=100, step=4, label="Weekly team capacity")
        )
        self.save_settings_button = ref(Button("Save settings"))
        self.save_settings_button.setAttribute("data-testid", "save-settings")
        self.save_settings_button.on_click(self.save_settings)
        self.settings_sheet = ref(
            Sheet(
                SheetTrigger("⚙"),
                SheetContent(
                    "Workspace settings",
                    SheetHeader(
                        SheetTitle("Workspace settings"),
                        SheetDescription("Tune notifications and planning defaults."),
                    ),
                    div(
                        tw("grid gap-6"),
                        div(
                            tw("flex items-center justify-between gap-4"),
                            div(
                                h3(tw("text-sm font-medium"), "Launch notifications"),
                                p(
                                    tw("text-xs text-slate-500"),
                                    "Notify you when a task is blocked.",
                                ),
                            ),
                            self.notification_switch,
                        ),
                        form_field(
                            "Weekly capacity",
                            self.capacity_slider,
                            "Controls the threshold used by planning reports.",
                        ),
                        Alert(
                            AlertTitle("Settings are local to this demo"),
                            AlertDescription("Refreshing restores the example defaults."),
                        ),
                    ),
                    SheetFooter(SheetClose("Cancel"), self.save_settings_button),
                    side="right",
                ),
            )
        )
        self.settings_sheet.trigger.setAttribute("aria-label", "Open workspace settings")
        self.settings_sheet.trigger.setAttribute("data-testid", "settings-trigger")

        self.task_count_label = ref(span(tw("font-medium"), "5 tasks"))
        self.task_count_label.setAttribute("data-testid", "task-count")
        self.task_table_body = ref(
            TableBody(
                task_row("ORB-142", "Finalize launch checklist", "Maya", "In progress", "High"),
                task_row("ORB-138", "Review onboarding copy", "Noah", "In review", "Medium"),
                task_row("ORB-131", "Resolve billing webhook", "Inez", "Blocked", "High"),
                task_row("ORB-127", "Publish API examples", "Theo", "Todo", "Medium"),
                task_row("ORB-119", "QA responsive navigation", "Maya", "Done", "Low"),
            )
        )

        sidebar = self.build_sidebar()
        header = self.build_header()
        overview = self.build_overview()
        tasks = self.build_tasks()
        collaboration = self.build_collaboration()
        self.tabs = ref(
            TabGroup(
                Tab("overview", "Overview", overview),
                Tab("tasks", "Tasks", tasks),
                Tab("collaboration", "Collaboration", collaboration),
                default_value="overview",
            )
        )
        inset = SidebarInset(
            header,
            div(
                tw("mx-auto grid w-full max-w-[1500px] gap-6 p-4 md:p-6"),
                div(
                    tw("flex flex-col justify-between gap-4 sm:flex-row sm:items-end"),
                    div(
                        Badge("Launch week", variant="outline"),
                        h1(
                            tw("mt-2 text-3xl font-bold tracking-tight text-slate-950"),
                            "Orbit launch",
                        ),
                        p(
                            tw("mt-1 text-sm text-slate-500"),
                            "A single workspace for product, engineering, and go-to-market.",
                        ),
                    ),
                    div(tw("flex items-center gap-2"), self.new_task_dialog, self.settings_sheet),
                ),
                self.tabs,
            ),
        )
        self.layout = ref(SidebarLayout(sidebar, inset))
        self.add(
            tw("block min-h-screen bg-slate-50 text-slate-950"),
            {"data-testid": "workspace"},
            self.layout,
            self.toaster,
        )

    def build_sidebar(self):
        workspace_menu = DropdownMenu(
            DropdownMenuTrigger("◈ Orbit Labs"),
            DropdownMenuContent(
                DropdownMenuLabel("Workspaces"),
                DropdownMenuItem("orbit", "Orbit Labs"),
                DropdownMenuItem("atlas", "Atlas Studio"),
                DropdownMenuSeparator(),
                DropdownMenuItem("create", "Create workspace"),
            ),
        )
        user_menu = DropdownMenu(
            DropdownMenuTrigger("ML  Maya Lee"),
            DropdownMenuContent(
                DropdownMenuLabel("maya@orbit.test"),
                DropdownMenuSeparator(),
                DropdownMenuItem("profile", "Profile"),
                DropdownMenuItem("billing", "Billing"),
                DropdownMenuItem("logout", "Log out"),
            ),
            side="top",
        )
        launch_progress = ProgressBar(74, label="Launch readiness")
        return Sidebar(
            SidebarHeader(
                workspace_menu,
                div(
                    tw(
                        "flex h-8 items-center gap-2 rounded-md border border-slate-300 "
                        "bg-white px-2 text-xs text-slate-500"
                    ),
                    "⌕ Search",
                    KbdGroup(Kbd("⌘"), Kbd("K")),
                ),
            ),
            SidebarContent(
                SidebarGroup(
                    SidebarGroupLabel("Workspace"),
                    SidebarGroupContent(
                        SidebarMenu(
                            SidebarMenuItem(SidebarMenuButton("#", "⌂ Overview", current=True)),
                            SidebarMenuItem(
                                SidebarMenuButton("#tasks", "✓ Tasks", SidebarMenuBadge("5"))
                            ),
                            SidebarMenuItem(SidebarMenuButton("#calendar", "□ Calendar")),
                            SidebarMenuItem(SidebarMenuButton("#reports", "⌁ Reports")),
                        )
                    ),
                ),
                SidebarSeparator(),
                SidebarGroup(
                    SidebarGroupLabel("Teams"),
                    SidebarGroupContent(
                        SidebarMenu(
                            SidebarMenuItem(SidebarMenuButton("#product", "● Product")),
                            SidebarMenuItem(SidebarMenuButton("#engineering", "● Engineering")),
                            SidebarMenuItem(SidebarMenuButton("#growth", "● Growth")),
                        )
                    ),
                ),
                div(
                    tw("mx-4 mt-4 grid gap-2 rounded-lg border border-slate-200 bg-white p-3"),
                    div(
                        tw("flex justify-between text-xs"),
                        span(tw("font-medium"), "Launch readiness"),
                        span("74%"),
                    ),
                    launch_progress,
                    p(tw("text-xs text-slate-500"), "11 days until public launch"),
                ),
            ),
            SidebarFooter(user_menu),
        )

    def build_header(self):
        team = AvatarGroup(
            Avatar(fallback="ML", alt="Maya Lee", size="sm"),
            Avatar(fallback="NK", alt="Noah Kim", size="sm"),
            Avatar(fallback="IR", alt="Inez Reed", size="sm"),
        )
        help_tooltip = Tooltip(
            TooltipTrigger("?"),
            TooltipContent("Open workspace documentation"),
        )
        return tag(
            "header",
            tw(
                "sticky top-0 z-40 flex h-16 items-center justify-between border-b "
                "border-slate-200 bg-white/95 px-4 backdrop-blur md:px-6"
            ),
            div(
                tw("flex items-center gap-3"),
                SidebarTrigger("☰"),
                Separator(orientation="vertical"),
                Breadcrumb(
                    BreadcrumbList(
                        BreadcrumbItem(BreadcrumbLink("#", "Orbit Labs")),
                        BreadcrumbSeparator(),
                        BreadcrumbItem(BreadcrumbPage("Launch")),
                    )
                ),
            ),
            div(tw("flex items-center gap-3"), team, help_tooltip),
        )

    def build_overview(self):
        metrics = div(
            tw("grid gap-4 sm:grid-cols-2 xl:grid-cols-4"),
            metric_card("Tasks completed", "38", "+12%", "8 completed this week"),
            metric_card("Launch readiness", "74%", "+6%", "On track for August 1"),
            metric_card("Open blockers", "3", "-2", "Billing is the highest risk"),
            metric_card("Team capacity", "82%", "+4%", "Across three working groups"),
        )
        delivery_chart = Card(
            CardHeader(
                CardTitle("Weekly delivery"),
                CardDescription("Completed launch tasks over the last six weeks."),
            ),
            CardContent(
                BarChart(
                    [8, 12, 9, 17, 15, 21],
                    ["W1", "W2", "W3", "W4", "W5", "W6"],
                    height=70,
                )
            ),
        )
        risks = Card(
            CardHeader(CardTitle("Launch health"), CardDescription("The current critical path.")),
            CardContent(
                Alert(
                    AlertTitle("Billing webhook needs attention"),
                    AlertDescription("The retry path is blocking the production readiness review."),
                ),
                AccordionGroup(
                    AccordionItem(
                        "product",
                        "Product and onboarding",
                        "Copy is approved. The final walkthrough is scheduled for Tuesday.",
                        open=True,
                    ),
                    AccordionItem(
                        "engineering",
                        "Engineering readiness",
                        "Two integration tasks and one performance audit remain.",
                    ),
                    AccordionItem(
                        "growth",
                        "Go-to-market",
                        "Campaign assets are ready and partner review begins tomorrow.",
                    ),
                ),
            ),
        )
        milestones = Carousel(
            milestone(
                "Production readiness review",
                "Engineering, support, and product owners confirm the release checklist.",
                "July 24",
            ),
            milestone(
                "Customer preview",
                "Invite the design partners and capture feedback in the launch room.",
                "July 28",
            ),
            milestone(
                "Public launch",
                "Publish documentation, enable billing, and start launch monitoring.",
                "August 1",
            ),
            label="Launch milestones",
            loop=True,
        )
        notes = Collapsible(
            CollapsibleTrigger("▸ Show launch notes"),
            CollapsibleContent(
                "The support rotation begins at 08:00 UTC. Escalate production issues in "
                "the #launch-ops room."
            ),
        )
        return div(
            tw("grid gap-5"),
            metrics,
            div(tw("grid gap-5 xl:grid-cols-[1.4fr_1fr]"), delivery_chart, risks),
            Card(
                CardHeader(CardTitle("Next milestones"), CardDescription("Move through the plan.")),
                CardContent(milestones),
            ),
            notes,
        )

    def build_tasks(self):
        search = Input(placeholder="Filter tasks...", name="task-search")
        search.setAttribute("aria-label", "Filter tasks")
        status_filter = Select(
            SelectTrigger("Status"),
            SelectContent(
                SelectItem("all", "All statuses"),
                SelectItem("todo", "Todo"),
                SelectItem("progress", "In progress"),
                SelectItem("blocked", "Blocked"),
            ),
            value="all",
        )
        density = ToggleGroup(
            Toggle("Comfortable", value="comfortable", pressed=True, size="sm"),
            Toggle("Compact", value="compact", size="sm"),
        )
        table = Table(
            TableHeader(
                TableRow(
                    TableHead(Checkbox(name="select-all")),
                    TableHead("Task"),
                    TableHead("Title"),
                    TableHead("Owner"),
                    TableHead("Status"),
                    TableHead("Priority"),
                    TableHead(""),
                )
            ),
            self.task_table_body,
        )
        pagination = Pagination(
            PaginationContent(
                PaginationItem(PaginationPrevious("#tasks")),
                PaginationItem(PaginationLink("#tasks", "1", current=True, label="Page 1")),
                PaginationItem(PaginationLink("#tasks", "2", label="Page 2")),
                PaginationItem(PaginationEllipsis()),
                PaginationItem(PaginationNext("#tasks")),
            )
        )
        return div(
            tw("grid gap-4"),
            div(
                tw("flex flex-col justify-between gap-3 lg:flex-row lg:items-center"),
                div(tw("flex flex-1 flex-wrap items-center gap-2"), search, status_filter),
                density,
            ),
            div(tw("overflow-hidden rounded-lg border border-slate-200"), table),
            div(
                tw("flex flex-col justify-between gap-3 sm:flex-row sm:items-center"),
                p(tw("text-sm text-slate-500"), self.task_count_label, " in this view"),
                pagination,
            ),
        )

    def build_collaboration(self):
        maya = HoverCard(
            HoverCardTrigger("Maya Lee"),
            HoverCardContent(
                div(
                    tw("flex gap-3"),
                    Avatar(AvatarBadge(), fallback="ML", alt="Maya Lee"),
                    div(
                        h3(tw("font-semibold"), "Maya Lee"),
                        p(tw("text-sm text-slate-500"), "Product lead · New York"),
                    ),
                )
            ),
            align="start",
        )
        conversation = MessageGroup(
            Message(
                MessageAvatar("ML"),
                MessageContent(
                    MessageHeader(maya, span("09:42")),
                    Bubble(
                        BubbleContent(
                            "The customer preview is confirmed. Can engineering share the latest "
                            "readiness notes before tomorrow?"
                        ),
                        BubbleReactions("✓ 3"),
                    ),
                ),
            ),
            Message(
                MessageAvatar("NK"),
                MessageContent(
                    MessageHeader(span("Noah Kim"), span("09:48")),
                    Bubble(
                        BubbleContent(
                            "Yes — I attached the updated checklist. Billing retries are the only "
                            "remaining blocker."
                        )
                    ),
                    Attachment(
                        AttachmentMedia("PDF"),
                        AttachmentContent(
                            AttachmentTitle("production-readiness.pdf"),
                            AttachmentDescription("1.8 MB · Updated 4 minutes ago"),
                        ),
                        AttachmentActions(AttachmentAction("Download attachment", "↓")),
                    ),
                ),
            ),
            Message(
                MessageAvatar("You"),
                MessageContent(
                    MessageHeader(span("You"), span("09:53")),
                    Bubble(
                        BubbleContent("Perfect. I’ll add the retry decision to today’s review."),
                        variant="sent",
                    ),
                ),
                sent=True,
            ),
        )
        updates = ItemGroup(
            Item(
                ItemContent(
                    ItemTitle("Deployment preview ready"),
                    ItemDescription("Noah deployed commit 8f42a1 to the preview environment."),
                ),
                ItemActions(Badge("Engineering", variant="outline")),
                variant="outline",
            ),
            Item(
                ItemContent(
                    ItemTitle("Launch copy approved"),
                    ItemDescription("Maya closed the final review round."),
                ),
                ItemActions(Badge("Product", variant="outline")),
                variant="outline",
            ),
            Item(
                ItemContent(
                    ItemTitle("Partner briefing scheduled"),
                    ItemDescription("Inez invited 12 customer advocates for July 29."),
                ),
                ItemActions(Badge("Growth", variant="outline")),
                variant="outline",
            ),
        )
        return div(
            tw("grid gap-5 xl:grid-cols-[1.4fr_1fr]"),
            Card(
                CardHeader(
                    CardTitle("Launch room"), CardDescription("A focused team conversation.")
                ),
                CardContent(ScrollArea(conversation, height="28rem")),
            ),
            Card(
                CardHeader(
                    CardTitle("Recent updates"), CardDescription("Activity across the plan.")
                ),
                CardContent(updates),
            ),
        )

    @effect(task_count)
    def render_task_count(self):
        self.task_count_label.textContent = str(self.task_count) + " tasks"

    def create_task(self, event: Event):
        title = self.task_title.get_value()
        if title == "":
            self.task_title.set_invalid(True)
            self.toaster.notify(
                "A title is required", "Add a short title before creating the task."
            )
            return
        self.task_title.set_invalid(False)
        self.task_count += 1
        task_id = "ORB-" + str(142 + self.task_count)
        self.task_table_body.append(task_row(task_id, title, "You", "Todo", "Medium"))
        self.new_task_dialog.close()
        self.toaster.notify("Task created", title + " was added to the launch plan.")
        self.task_title.set_value("")

    def save_settings(self, event: Event):
        capacity = self.capacity_slider.get_value()
        self.settings_sheet.close()
        self.toaster.notify("Settings saved", "Weekly capacity is now " + capacity + "%.")


def main():
    return WorkspaceApp()


if __name__ == "__main__":
    from pyjs.server import serve

    serve("workspace")
