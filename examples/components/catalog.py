from pyjs import js
from pyjs.web.domx import a, button, div, h1, h2, h3, input, p, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLInputElement
from pyjs.web.ui import Widget
from pyjs.web.ui.accordion import AccordionGroup, AccordionItem
from pyjs.web.ui.alert import Alert, AlertAction, AlertDescription, AlertTitle
from pyjs.web.ui.alert_dialog import (
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
)
from pyjs.web.ui.aspect_ratio import AspectRatio
from pyjs.web.ui.attachment import (
    Attachment,
    AttachmentContent,
    AttachmentDescription,
    AttachmentGroup,
    AttachmentMedia,
    AttachmentTitle,
)
from pyjs.web.ui.avatar import Avatar, AvatarBadge, AvatarGroup, AvatarGroupCount
from pyjs.web.ui.badge import Badge
from pyjs.web.ui.breadcrumb import (
    Breadcrumb,
    BreadcrumbItem,
    BreadcrumbLink,
    BreadcrumbList,
    BreadcrumbPage,
    BreadcrumbSeparator,
)
from pyjs.web.ui.bubble import Bubble, BubbleContent, BubbleGroup
from pyjs.web.ui.button import Button, ButtonGroup, ButtonGroupText
from pyjs.web.ui.calendar import Calendar
from pyjs.web.ui.card import (
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
)
from pyjs.web.ui.carousel import Carousel, CarouselItem
from pyjs.web.ui.chart import BarChart, LineChart
from pyjs.web.ui.checkbox import Checkbox
from pyjs.web.ui.collapsible import Collapsible, CollapsibleContent, CollapsibleTrigger
from pyjs.web.ui.combobox import Combobox
from pyjs.web.ui.command import Command, CommandItem
from pyjs.web.ui.context_menu import (
    ContextMenu,
    ContextMenuContent,
    ContextMenuItem,
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
from pyjs.web.ui.direction import Direction
from pyjs.web.ui.drawer import Drawer, DrawerContent, DrawerTitle, DrawerTrigger
from pyjs.web.ui.empty import (
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
)
from pyjs.web.ui.field import (
    Field,
    FieldContent,
    FieldDescription,
    FieldError,
    FieldGroup,
    FieldLabel,
    FieldSet,
    FieldTitle,
)
from pyjs.web.ui.hover_card import HoverCard, HoverCardContent, HoverCardTrigger
from pyjs.web.ui.input import Input
from pyjs.web.ui.input_group import InputGroup, InputGroupAddon, InputGroupInput
from pyjs.web.ui.input_otp import InputOTP
from pyjs.web.ui.item import Item, ItemContent, ItemDescription, ItemMedia, ItemTitle
from pyjs.web.ui.kbd import Kbd, KbdGroup
from pyjs.web.ui.label import Label
from pyjs.web.ui.marker import Marker, MarkerContent, MarkerIcon
from pyjs.web.ui.menubar import Menubar, MenubarItem, MenubarMenu
from pyjs.web.ui.message import Message, MessageContent, MessageGroup, MessageHeader
from pyjs.web.ui.message_scroller import MessageScroller
from pyjs.web.ui.native_select import NativeSelect, NativeSelectOption
from pyjs.web.ui.navigation_menu import (
    NavigationMenu,
    NavigationMenuLink,
    NavigationMenuList,
)
from pyjs.web.ui.pagination import (
    Pagination,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationLink,
    PaginationNext,
    PaginationPrevious,
)
from pyjs.web.ui.popover import (
    Popover,
    PopoverClose,
    PopoverContent,
    PopoverDescription,
    PopoverHeader,
    PopoverTitle,
    PopoverTrigger,
)
from pyjs.web.ui.progress import ProgressBar
from pyjs.web.ui.questionnaire import (
    Questionnaire,
    QuestionnaireChoice,
    QuestionnaireChoiceDescription,
    QuestionnaireChoices,
    QuestionnaireDescription,
    QuestionnaireError,
    QuestionnaireInput,
    QuestionnaireItem,
    QuestionnaireTitle,
)
from pyjs.web.ui.radio_group import RadioGroup, RadioGroupItem
from pyjs.web.ui.resizable import ResizableHandle, ResizablePanel, ResizablePanelGroup
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
from pyjs.web.ui.sidebar import Sidebar
from pyjs.web.ui.skeleton import Skeleton
from pyjs.web.ui.slider import Slider
from pyjs.web.ui.sonner import Toaster
from pyjs.web.ui.spinner import Spinner
from pyjs.web.ui.switch import Switch
from pyjs.web.ui.table import (
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableFooter,
    TableHead,
    TableHeader,
    TableRow,
)
from pyjs.web.ui.tabs import Tab, TabGroup
from pyjs.web.ui.textarea import Textarea
from pyjs.web.ui.toggle import Toggle, ToggleGroup
from pyjs.web.ui.tooltip import Tooltip, TooltipContent, TooltipTrigger
from pyjs.web.ui.typography import TypographyH3, TypographyInlineCode, TypographyLead, TypographyP

from .catalog_sources import catalog_source


@js
def field(label: str, input_element: HTMLInputElement):
    return tag(
        "label",
        tw("grid gap-2 text-left text-sm font-medium text-slate-900"),
        label,
        input_element,
    )


@js
def example_card(title: str, description: str, command: str):
    return div(
        tw("rounded-lg border border-slate-200 bg-white p-5 shadow-sm"),
        h3(tw("font-semibold text-slate-950"), title),
        p(tw("mt-2 text-sm leading-6 text-slate-600"), description),
        tag(
            "code",
            tw("mt-4 block overflow-x-auto rounded-md bg-slate-950 p-3 text-xs text-slate-50"),
            command,
        ),
    )


@js
def component_showcase(
    component_id: str,
    title: str,
    description: str,
    *children,
    source_module: str = "",
):
    if source_module == "":
        source_module = component_id.replace("-", "_")
    module_name = "pyjs.web.ui." + source_module
    source_url = (
        "https://github.com/pyjs/pyjs/blob/main/pyjs/web/ui/"
        + source_module
        + ".py"
    )
    return tag(
        "section",
        tw("mt-16 scroll-mt-24 border-t border-slate-200 pt-12"),
        {"data-catalog-component": component_id, "id": component_id},
        h2(tw("text-2xl font-bold tracking-tight text-slate-950"), title),
        p(tw("mt-3 max-w-2xl leading-7 text-slate-600"), description),
        div(
            tw("mt-7 rounded-lg border border-slate-200 bg-white p-8"),
            *children,
        ),
        python_example(catalog_source(component_id)),
        div(
            tw(
                "mt-4 flex flex-wrap items-center justify-between gap-3 "
                "text-xs text-slate-500"
            ),
            tag("code", tw("rounded bg-slate-100 px-2 py-1"), module_name),
            a(
                tw("font-medium text-slate-700 underline underline-offset-4"),
                {"href": source_url},
                "View Python source",
            ),
        ),
    )


@js
def python_example(source: str):
    return tag(
        "details",
        tw("mt-4 overflow-hidden rounded-lg border border-slate-800 bg-slate-950"),
        {"data-catalog-source": ""},
        tag(
            "summary",
            tw(
                "cursor-pointer select-none px-4 py-3 text-xs font-medium "
                "text-slate-300 hover:text-white"
            ),
            "Python example",
        ),
        tag(
            "pre",
            tw(
                "overflow-x-auto border-t border-slate-800 p-5 text-sm "
                "leading-6 text-slate-100"
            ),
            tag("code", source),
        ),
    )


@js
def catalog_sidebar_link(component_id: str, title: str):
    return a(
        tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
        {"href": "#" + component_id},
        title,
    )


@js
def api_reference(module: str, accessibility: str, *signatures: str):
    source_url = (
        "https://github.com/pyjs/pyjs/blob/main/"
        + module.replace(".", "/")
        + ".py"
    )
    return div(
        tw(
            "mt-8 grid gap-4 rounded-lg border border-slate-200 bg-slate-50 "
            "p-5 md:grid-cols-2"
        ),
        div(
            h3(tw("font-semibold text-slate-950"), "API"),
            tag(
                "code",
                tw("mt-3 block whitespace-pre-wrap text-xs leading-6 text-slate-700"),
                "\n".join(signatures),
            ),
            a(
                tw(
                    "mt-3 inline-block text-xs font-medium underline "
                    "underline-offset-4"
                ),
                {"href": source_url},
                "View Python source",
            ),
        ),
        div(
            h3(tw("font-semibold text-slate-950"), "Accessibility"),
            p(tw("mt-3 text-sm leading-6 text-slate-600"), accessibility),
        ),
    )


@js
def remaining_sidebar_links():
    return div(
        tw("contents"),
        catalog_sidebar_link("attachment", "Attachment"),
        catalog_sidebar_link("bubble", "Bubble"),
        catalog_sidebar_link("calendar", "Calendar"),
        catalog_sidebar_link("carousel", "Carousel"),
        catalog_sidebar_link("chart", "Chart"),
        catalog_sidebar_link("combobox", "Combobox"),
        catalog_sidebar_link("command", "Command"),
        catalog_sidebar_link("context-menu", "Context Menu"),
        catalog_sidebar_link("date-picker", "Date Picker"),
        catalog_sidebar_link("direction", "Direction"),
        catalog_sidebar_link("drawer", "Drawer"),
        catalog_sidebar_link("input-group", "Input Group"),
        catalog_sidebar_link("input-otp", "Input OTP"),
        catalog_sidebar_link("item", "Item"),
        catalog_sidebar_link("marker", "Marker"),
        catalog_sidebar_link("menubar", "Menubar"),
        catalog_sidebar_link("message", "Message"),
        catalog_sidebar_link("message-scroller", "Message Scroller"),
        catalog_sidebar_link("native-select", "Native Select"),
        catalog_sidebar_link("navigation-menu", "Navigation Menu"),
        catalog_sidebar_link("pagination", "Pagination"),
        catalog_sidebar_link("questionnaire", "Questionnaire"),
        catalog_sidebar_link("resizable", "Resizable"),
        catalog_sidebar_link("scroll-area", "Scroll Area"),
        catalog_sidebar_link("select", "Select"),
        catalog_sidebar_link("sidebar", "Sidebar"),
        catalog_sidebar_link("slider", "Slider"),
        catalog_sidebar_link("sonner", "Sonner"),
        catalog_sidebar_link("typography", "Typography"),
    )


@js
class NotificationDemo(Widget):
    def __init__(self):
        super().__init__()
        self.toaster = ref(Toaster())
        show_button = Button("Show notification", variant="outline")
        show_button.on_click(self.show)
        self.add(show_button, self.toaster)

    def show(self, event: Event):
        self.toaster.notify("Project saved", "The latest changes are now live.")


@js
class CatalogPagination(Widget):
    def __init__(self):
        super().__init__()
        self.previous = ref(PaginationPrevious("#pagination"))
        self.page_one = ref(PaginationLink("#pagination", "1"))
        self.page_two = ref(PaginationLink("#pagination", "2"))
        self.next = ref(PaginationNext("#pagination"))
        self.previous.addEventListener("click", self.previous_clicked)
        self.page_one.addEventListener("click", self.page_one_clicked)
        self.page_two.addEventListener("click", self.page_two_clicked)
        self.next.addEventListener("click", self.next_clicked)
        self.add(
            Pagination(
                PaginationContent(
                    PaginationItem(self.previous),
                    PaginationItem(self.page_one),
                    PaginationItem(self.page_two),
                    PaginationItem(PaginationEllipsis()),
                    PaginationItem(self.next),
                )
            )
        )
        self.set_page(1)

    def set_page(self, page: int):
        self.setAttribute("data-page", str(page))
        if page == 1:
            self.page_one.setAttribute("aria-current", "page")
            self.page_two.removeAttribute("aria-current")
            self.previous.setAttribute("aria-disabled", "true")
            self.next.removeAttribute("aria-disabled")
        else:
            self.page_one.removeAttribute("aria-current")
            self.page_two.setAttribute("aria-current", "page")
            self.previous.removeAttribute("aria-disabled")
            self.next.setAttribute("aria-disabled", "true")

    def previous_clicked(self, event: Event):
        event.preventDefault()
        self.set_page(1)

    def page_one_clicked(self, event: Event):
        event.preventDefault()
        self.set_page(1)

    def page_two_clicked(self, event: Event):
        event.preventDefault()
        self.set_page(2)

    def next_clicked(self, event: Event):
        event.preventDefault()
        self.set_page(2)


@js
def remaining_component_showcases():
    return div(
        tw("contents"),
        component_showcase(
            "attachment",
            "Attachment",
            "Represents a file with metadata and related actions.",
            AttachmentGroup(
                Attachment(
                    AttachmentMedia("PDF"),
                    AttachmentContent(
                        AttachmentTitle("design-notes.pdf"),
                        AttachmentDescription("240 KB · PDF"),
                    ),
                )
            ),
        ),
        component_showcase(
            "bubble",
            "Bubble",
            "Displays compact conversational content and sent-state styling.",
            BubbleGroup(
                Bubble(BubbleContent("Can we ship this today?")),
                Bubble(
                    BubbleContent("Yes—the browser tests are green."),
                    align="end",
                    variant="tinted",
                ),
            ),
        ),
        component_showcase(
            "calendar",
            "Calendar",
            "Selects a day from a semantic monthly grid.",
            Calendar("July", 2026, starts_on=3, selected_day=21),
        ),
        component_showcase(
            "carousel",
            "Carousel",
            "Moves through a finite collection of slides with native buttons.",
            Carousel(
                CarouselItem(div(tw("rounded-md bg-slate-100 p-12 text-center"), "First slide")),
                CarouselItem(div(tw("rounded-md bg-slate-200 p-12 text-center"), "Second slide")),
            ),
        ),
        component_showcase(
            "chart",
            "Chart",
            "Renders updateable accessible SVG graphics without a chart dependency.",
            div(
                tw("grid gap-6 md:grid-cols-2"),
                BarChart(
                    [18, 32, 24, 41],
                    ["Q1", "Q2", "Q3", "Q4"],
                    label="Quarterly usage",
                ),
                LineChart(
                    [12, 18, 16, 29, 35],
                    ["Mon", "Tue", "Wed", "Thu", "Fri"],
                    label="Daily usage",
                ),
            ),
        ),
        component_showcase(
            "combobox",
            "Combobox",
            "Filters and selects from a searchable collection.",
            Combobox(
                CommandItem("Python", "Python"),
                CommandItem("JavaScript", "JavaScript"),
                CommandItem("Rust", "Rust"),
                placeholder="Choose a language...",
            ),
        ),
        component_showcase(
            "command",
            "Command",
            "Filters a keyboard-friendly command collection.",
            Command(
                CommandItem("Open file", "Open file"),
                CommandItem("Save all", "Save all"),
                CommandItem("Close window", "Close window"),
            ),
        ),
        component_showcase(
            "context-menu",
            "Context Menu",
            "Opens an action menu from the native contextmenu event.",
            ContextMenu(
                ContextMenuTrigger(
                    div(tw("rounded-md border border-dashed p-12 text-center"), "Right click here")
                ),
                ContextMenuContent(
                    ContextMenuItem("copy", "Copy"),
                    ContextMenuItem("rename", "Rename"),
                ),
            ),
        ),
        component_showcase(
            "date-picker",
            "Date Picker",
            "Composes Calendar and Popover into a compact date control.",
            DatePicker(Calendar("July", 2026, starts_on=3)),
        ),
        component_showcase(
            "direction",
            "Direction",
            "Applies left-to-right or right-to-left direction to a subtree.",
            Direction(
                div(tw("rounded-md border p-4"), "واجهة من اليمين إلى اليسار"), direction="rtl"
            ),
        ),
        component_showcase(
            "drawer",
            "Drawer",
            "Presents a modal task surface from the bottom edge.",
            Drawer(DrawerTrigger("Open drawer"), DrawerContent("Account", DrawerTitle("Account"))),
        ),
        component_showcase(
            "input-group",
            "Input Group",
            "Combines an input with contextual prefixes and controls.",
            Label(
                "Website",
                InputGroup(
                    InputGroupAddon("https://"),
                    InputGroupInput(placeholder="example.com"),
                ),
            ),
        ),
        component_showcase(
            "input-otp",
            "Input OTP",
            "Captures a one-time code with a single accessible input and visual slots.",
            InputOTP(6),
        ),
        component_showcase(
            "item",
            "Item",
            "Groups media, text, and actions into a reusable list row.",
            Item(
                ItemMedia("AL"),
                ItemContent(ItemTitle("Ada Lovelace"), ItemDescription("Administrator")),
                variant="outline",
            ),
        ),
        component_showcase(
            "marker",
            "Marker",
            "Annotates compact status or metadata.",
            Marker(MarkerIcon("●"), MarkerContent("Live")),
        ),
        component_showcase(
            "menubar",
            "Menubar",
            "Groups application menus into a familiar horizontal control.",
            Menubar(
                MenubarMenu("File", MenubarItem("new", "New"), MenubarItem("open", "Open")),
                MenubarMenu("Edit", MenubarItem("undo", "Undo"), MenubarItem("redo", "Redo")),
            ),
        ),
        component_showcase(
            "message",
            "Message",
            "Composes sender metadata and conversational content.",
            MessageGroup(
                Message(
                    MessageContent(
                        MessageHeader("Ada · 2:14 PM"),
                        Bubble(BubbleContent("Ready to review."), variant="secondary"),
                    )
                )
            ),
        ),
        component_showcase(
            "message-scroller",
            "Message Scroller",
            "Keeps a message log scrollable and offers a jump-to-latest action.",
            MessageScroller(
                Bubble(BubbleContent("Earlier update"), variant="muted"),
                Bubble(BubbleContent("Latest update"), align="end"),
            ),
        ),
        component_showcase(
            "native-select",
            "Native Select",
            "Styles the platform select when native behavior is the best fit.",
            NativeSelect(
                NativeSelectOption("comfortable", "Comfortable", selected=True),
                NativeSelectOption("compact", "Compact"),
                label="Density",
            ),
        ),
        component_showcase(
            "navigation-menu",
            "Navigation Menu",
            "Provides semantic site navigation with current-page state.",
            NavigationMenu(
                NavigationMenuList(
                    NavigationMenuLink("#navigation-menu", "Overview", current=True),
                    NavigationMenuLink("#examples", "Examples"),
                )
            ),
        ),
        component_showcase(
            "pagination",
            "Pagination",
            "Navigates a long collection through addressable pages.",
            CatalogPagination(),
        ),
        component_showcase(
            "questionnaire",
            "Questionnaire",
            "Guides a user through accessible, validated questions one at a time.",
            Questionnaire(
                QuestionnaireItem(
                    "goal",
                    QuestionnaireTitle("What are you building?"),
                    QuestionnaireDescription(
                        "Choose the answer that best describes your project."
                    ),
                    QuestionnaireChoices(
                        QuestionnaireChoice(
                            "application",
                            "An application",
                            QuestionnaireChoiceDescription(
                                "A complete web or mobile product."
                            ),
                        ),
                        QuestionnaireChoice(
                            "component",
                            "A reusable component",
                            QuestionnaireChoiceDescription(
                                "A focused widget for another application."
                            ),
                        ),
                    ),
                    QuestionnaireError("Choose an answer to continue."),
                    required=True,
                ),
                QuestionnaireItem(
                    "detail",
                    QuestionnaireTitle("Anything else we should know?"),
                    QuestionnaireDescription("This final answer is optional."),
                    QuestionnaireInput("Add a short note..."),
                ),
            ),
        ),
        component_showcase(
            "resizable",
            "Resizable",
            "Defines accessible panel and separator structure.",
            ResizablePanelGroup(
                ResizablePanel(div(tw("p-6"), "Navigation"), initial_size=35),
                ResizableHandle(with_handle=True),
                ResizablePanel(div(tw("p-6"), "Content"), initial_size=65),
            ),
        ),
        component_showcase(
            "scroll-area",
            "Scroll Area",
            "Constrains overflowing content while preserving native scrolling.",
            ScrollArea(
                div(
                    tw("grid gap-3 p-3"),
                    div("Release 1"),
                    div("Release 2"),
                    div("Release 3"),
                    div("Release 4"),
                    div("Release 5"),
                    div("Release 6"),
                    div("Release 7"),
                    div("Release 8"),
                ),
                height="8rem",
            ),
        ),
        component_showcase(
            "select",
            "Select",
            "Chooses one value from a styled floating listbox.",
            Select(
                SelectTrigger("Choose a fruit"),
                SelectContent(SelectItem("apple", "Apple"), SelectItem("pear", "Pear")),
            ),
        ),
        component_showcase(
            "sidebar",
            "Sidebar",
            "Provides the structural surface used by application navigation.",
            Sidebar(div(tw("p-5 font-medium"), "Workspace navigation")),
        ),
        component_showcase(
            "slider",
            "Slider",
            "Selects a numeric value using the native range control.",
            Slider(45, label="Volume"),
        ),
        component_showcase(
            "sonner",
            "Sonner",
            "Announces and displays dismissible notifications.",
            NotificationDemo(),
        ),
        component_showcase(
            "typography",
            "Typography",
            "Applies a consistent prose hierarchy to semantic elements.",
            div(
                tw("grid gap-3"),
                TypographyH3("The Joke Tax Chronicles"),
                TypographyLead("A king once taxed every joke told in the kingdom."),
                TypographyP(
                    "The people called this levy the ", TypographyInlineCode("joke tax"), "."
                ),
            ),
        ),
    )


@js
class CatalogForm(Widget):
    def __init__(self):
        super().__init__()
        self.email = ref(Input(input_type="email", placeholder="you@example.com", name="email"))
        self.bio = ref(Textarea(placeholder="Tell us a little about yourself", name="bio"))
        self.terms = ref(Checkbox(name="terms"))
        self.updates = ref(Switch(name="updates", checked=True))
        self.error = ref(FieldError("Enter an email address and accept the terms."))
        self.error.setAttribute("hidden", "")
        self.status = ref(
            p(
                tw("text-sm text-slate-500"),
                {"aria-live": "polite", "data-testid": "form-status"},
                "Your settings have not been submitted.",
            )
        )
        self.form = ref(
            tag(
                "form",
                tw("grid w-full max-w-lg gap-6"),
                {"data-testid": "catalog-form", "novalidate": ""},
                FieldSet(
                    FieldGroup(
                        Field(
                            FieldLabel(
                                FieldTitle("Email"),
                                self.email,
                                FieldDescription("We will only use this for account updates."),
                            ),
                        ),
                        Field(
                            FieldLabel(
                                FieldTitle("Bio"),
                                self.bio,
                                FieldDescription("A short introduction shown on your profile."),
                            ),
                        ),
                        Field(
                            Label(
                                self.terms,
                                FieldContent(
                                    FieldTitle("Accept the terms"),
                                    FieldDescription(
                                        "I agree to the terms of service and privacy policy."
                                    ),
                                ),
                            ),
                            orientation="horizontal",
                        ),
                        Field(
                            Label(
                                self.updates,
                                FieldContent(
                                    FieldTitle("Product updates"),
                                    FieldDescription(
                                        "Send occasional news about new PyJS components."
                                    ),
                                ),
                            ),
                            orientation="horizontal",
                        ),
                        self.error,
                    )
                ),
                button(
                    tw(
                        "inline-flex h-9 w-fit items-center justify-center rounded-md "
                        "bg-slate-950 px-4 text-sm font-medium text-white shadow-sm "
                        "hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 "
                        "focus-visible:ring-slate-400"
                    ),
                    {"type": "submit"},
                    "Save preferences",
                ),
                self.status,
            )
        )
        self.form.addEventListener("submit", self.submit)
        self.add(self.form)

    def submit(self, event: Event):
        event.preventDefault()
        email_missing = self.email.get_value() == ""
        terms_missing = not self.terms.is_checked()
        self.email.set_invalid(email_missing)
        self.terms.set_invalid(terms_missing)

        if email_missing or terms_missing:
            self.error.removeAttribute("hidden")
            self.status.textContent = "Please correct the highlighted fields."
            return

        self.error.setAttribute("hidden", "")
        self.status.textContent = "Preferences saved for " + self.email.get_value() + "."


@js
class CatalogApp(Widget):
    def __init__(self, site_root: str = "https://pyjs.org/"):
        super().__init__()
        self.name_input = ref(
            input(
                tw(
                    "h-9 rounded-md border border-slate-300 bg-white px-3 text-sm shadow-sm "
                    "outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
                ),
                {"autofocus": "", "value": "Ada Lovelace"},
            )
        )
        self.username_input = ref(
            input(
                tw(
                    "h-9 rounded-md border border-slate-300 bg-white px-3 text-sm shadow-sm "
                    "outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
                ),
                {"value": "@ada"},
            )
        )
        self.save_button = ref(
            button(
                tw(
                    "inline-flex h-9 items-center justify-center rounded-md bg-slate-950 px-4 "
                    "text-sm font-medium text-white shadow-sm hover:bg-slate-800 "
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
                ),
                {"type": "button"},
                "Save changes",
            )
        )
        self.status = ref(
            p(
                tw("mt-4 text-sm text-slate-500"),
                {"aria-live": "polite", "data-testid": "profile-status"},
                "Open the dialog to edit the profile.",
            )
        )
        self.dialog = ref(
            Dialog(
                DialogTrigger("Edit profile"),
                DialogContent(
                    "Edit profile",
                    DialogHeader(
                        DialogTitle("Edit profile"),
                        DialogDescription(
                            "Make changes to your profile here. Click save when you are done."
                        ),
                    ),
                    div(
                        tw("grid gap-4 py-2"),
                        field("Name", self.name_input),
                        field("Username", self.username_input),
                    ),
                    DialogFooter(DialogClose("Cancel"), self.save_button),
                ),
            )
        )
        self.save_button.addEventListener("click", self.save_profile)

        sidebar = tag(
            "aside",
            tw("hidden w-64 shrink-0 border-r border-slate-200 bg-white px-6 py-8 lg:block"),
            tag(
                "nav",
                tw("sticky top-24 grid max-h-[calc(100vh-7rem)] gap-8 overflow-y-auto text-sm"),
                div(
                    p(tw("mb-3 font-semibold text-slate-950"), "Components"),
                    div(
                        tw("grid gap-1"),
                        a(
                            tw(
                                "block rounded-md bg-slate-100 px-3 py-2 font-medium text-slate-950"
                            ),
                            {"href": "#dialog"},
                            "Dialog",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#accordion"},
                            "Accordion",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#alert"},
                            "Alert",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#alert-dialog"},
                            "Alert Dialog",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#aspect-ratio"},
                            "Aspect Ratio",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#avatar"},
                            "Avatar",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#badge"},
                            "Badge",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#breadcrumb"},
                            "Breadcrumb",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#button"},
                            "Button",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#button-group"},
                            "Button Group",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#card"},
                            "Card",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#collapsible"},
                            "Collapsible",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#empty"},
                            "Empty",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#forms"},
                            "Forms",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#hover-card"},
                            "Hover Card",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#kbd"},
                            "Kbd",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#popover"},
                            "Popover",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#progress"},
                            "Progress",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#radio-group"},
                            "Radio Group",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#separator"},
                            "Separator",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#sheet"},
                            "Sheet",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#skeleton"},
                            "Skeleton",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#spinner"},
                            "Spinner",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#table"},
                            "Table",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#tabs"},
                            "Tabs",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#toggle"},
                            "Toggle",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#toggle-group"},
                            "Toggle Group",
                        ),
                        a(
                            tw("block rounded-md px-3 py-2 text-slate-600 hover:text-slate-950"),
                            {"href": "#tooltip"},
                            "Tooltip",
                        ),
                        remaining_sidebar_links(),
                    ),
                ),
                div(
                    p(tw("mb-3 font-semibold text-slate-950"), "Catalog"),
                    a(
                        tw("block px-3 py-2 text-slate-600 hover:text-slate-950"),
                        {"href": "#examples"},
                        "Example applications",
                    ),
                ),
            ),
        )
        dialog_preview = div(
            tw(
                "flex min-h-72 items-center justify-center rounded-lg border border-slate-200 "
                "bg-white p-8"
            ),
            div(tw("text-center"), self.dialog, self.status),
        )
        source = (
            "Dialog(\n"
            '    DialogTrigger("Edit profile"),\n'
            "    DialogContent(\n"
            '        "Edit profile",\n'
            "        DialogHeader(\n"
            '            DialogTitle("Edit profile"),\n'
            '            DialogDescription("Make changes to your profile."),\n'
            "        ),\n"
            "        profile_fields,\n"
            '        DialogFooter(DialogClose("Cancel"), save_button),\n'
            "    ),\n"
            ")"
        )
        content = tag(
            "main",
            tw("min-w-0 flex-1 px-6 py-12 sm:px-10 lg:px-14"),
            {"id": "main-content"},
            tag(
                "section",
                tw("mx-auto max-w-5xl scroll-mt-24"),
                {"data-catalog-component": "dialog", "id": "dialog"},
                p(
                    tw("text-sm font-medium text-slate-500"),
                    "Components / Dialog",
                ),
                h1(
                    tw("mt-3 text-4xl font-bold tracking-tight text-slate-950"),
                    "Dialog",
                ),
                p(
                    tw("mt-4 max-w-2xl text-lg leading-8 text-slate-600"),
                    "A modal window layered over the page. It traps focus, supports Escape and "
                    "backdrop dismissal, and restores focus to its trigger.",
                ),
                div(tw("mt-10"), dialog_preview),
                python_example(source),
                api_reference(
                    "pyjs.web.ui.dialog",
                    "Uses native dialog behavior, traps focus, supports Escape and backdrop "
                    "dismissal, and restores focus to the trigger.",
                    "Dialog(trigger: DialogTrigger, content: DialogContent)",
                    "DialogContent(label: str, *children, placement='center')",
                    "DialogTrigger(*children)",
                ),
                component_showcase(
                    "accordion",
                    "Accordion",
                    "Expands and collapses vertically stacked sections of content.",
                    AccordionGroup(
                        AccordionItem(
                            "product",
                            "Is it accessible?",
                            "Yes. It uses semantic buttons, expanded state, and keyboard focus.",
                            open=True,
                        ),
                        AccordionItem(
                            "styling",
                            "Can it be styled?",
                            "Yes. The component exposes stable data-slot and data-state attributes.",
                        ),
                        AccordionItem(
                            "animation",
                            "Can it be animated?",
                            "Yes. The state attributes provide hooks for CSS transitions.",
                        ),
                    ),
                ),
                component_showcase(
                    "alert",
                    "Alert",
                    "Displays an important message without interrupting the current task.",
                    div(
                        tw("grid gap-4"),
                        Alert(
                            AlertTitle("Heads up!"),
                            AlertDescription("The catalog now includes foundation components."),
                            AlertAction(
                                button(
                                    tw("text-xs font-medium underline underline-offset-4"),
                                    {"type": "button"},
                                    "Details",
                                )
                            ),
                        ),
                        Alert(
                            AlertTitle("Unable to save"),
                            AlertDescription("Check the form values and try again."),
                            variant="destructive",
                        ),
                    ),
                ),
                component_showcase(
                    "alert-dialog",
                    "Alert Dialog",
                    "Interrupts a destructive action until the user explicitly confirms or cancels.",
                    AlertDialog(
                        AlertDialogTrigger("Delete project"),
                        AlertDialogContent(
                            "Delete project",
                            AlertDialogHeader(
                                AlertDialogTitle("Are you absolutely sure?"),
                                AlertDialogDescription(
                                    "This permanently deletes the project and its deployment history."
                                ),
                            ),
                            AlertDialogFooter(
                                AlertDialogCancel("Cancel"),
                                AlertDialogAction("Continue"),
                            ),
                        ),
                    ),
                ),
                component_showcase(
                    "aspect-ratio",
                    "Aspect Ratio",
                    "Keeps media and previews at a consistent proportional size.",
                    div(
                        tw("max-w-xl"),
                        AspectRatio(
                            div(
                                tw(
                                    "absolute inset-0 flex items-end rounded-lg bg-gradient-to-br "
                                    "from-slate-950 via-slate-700 to-slate-400 p-6 text-white"
                                ),
                                p(tw("text-lg font-medium"), "16:9 preview"),
                            ),
                            ratio="16 / 9",
                        ),
                    ),
                ),
                component_showcase(
                    "avatar",
                    "Avatar",
                    "Represents a person with an image, initials fallback, size, and status.",
                    AvatarGroup(
                        Avatar(AvatarBadge(), fallback="AL", alt="Ada Lovelace"),
                        Avatar(fallback="GH", alt="Grace Hopper"),
                        Avatar(fallback="KT", alt="Katherine Johnson"),
                        AvatarGroupCount("+3"),
                    ),
                ),
                component_showcase(
                    "badge",
                    "Badge",
                    "A compact label for status, categories, and short metadata.",
                    div(
                        tw("flex flex-wrap items-center gap-3"),
                        Badge("Default"),
                        Badge("Secondary", variant="secondary"),
                        Badge("Destructive", variant="destructive"),
                        Badge("Outline", variant="outline"),
                        Badge("Ghost", variant="ghost"),
                        Badge("Link", variant="link"),
                    ),
                ),
                component_showcase(
                    "breadcrumb",
                    "Breadcrumb",
                    "Shows the current page's location within a navigational hierarchy.",
                    Breadcrumb(
                        BreadcrumbList(
                            BreadcrumbItem(BreadcrumbLink("#", "Catalog")),
                            BreadcrumbSeparator(),
                            BreadcrumbItem(BreadcrumbLink("#dialog", "Components")),
                            BreadcrumbSeparator(),
                            BreadcrumbItem(BreadcrumbPage("Breadcrumb")),
                        )
                    ),
                ),
                component_showcase(
                    "button",
                    "Button",
                    "Triggers an action using native button behavior and familiar visual variants.",
                    div(
                        tw("flex flex-wrap items-center gap-3"),
                        Button("Default"),
                        Button("Outline", variant="outline"),
                        Button("Secondary", variant="secondary"),
                        Button("Ghost", variant="ghost"),
                        Button("Delete", variant="destructive"),
                        Button("Learn more", variant="link"),
                    ),
                ),
                component_showcase(
                    "button-group",
                    "Button Group",
                    "Combines related controls into a visually connected group.",
                    ButtonGroup(
                        Button("Back", variant="outline"),
                        ButtonGroupText("Page 2 of 8"),
                        Button("Next", variant="outline"),
                    ),
                    source_module="button",
                ),
                component_showcase(
                    "card",
                    "Card",
                    "Groups related content and actions inside a bordered surface.",
                    div(
                        tw("max-w-md"),
                        Card(
                            CardHeader(
                                CardTitle("Team plan"),
                                CardDescription("For growing product teams."),
                                CardAction(Badge("Popular", variant="secondary")),
                            ),
                            CardContent(
                                "Unlimited projects, shared components, and priority support."
                            ),
                            CardFooter(
                                Button("Choose plan"),
                                Button("Details", variant="outline"),
                            ),
                        ),
                    ),
                ),
                component_showcase(
                    "collapsible",
                    "Collapsible",
                    "Reveals additional content without leaving the current context.",
                    Collapsible(
                        CollapsibleTrigger(
                            tag("span", "Three deployment files"),
                            tag("span", {"aria-hidden": "true"}, "+"),
                        ),
                        CollapsibleContent(
                            tag("code", tw("block rounded bg-slate-100 px-2 py-1"), "app.py"),
                            tag(
                                "code",
                                tw("mt-1 block rounded bg-slate-100 px-2 py-1"),
                                "pyproject.toml",
                            ),
                            tag(
                                "code", tw("mt-1 block rounded bg-slate-100 px-2 py-1"), "README.md"
                            ),
                        ),
                    ),
                ),
                component_showcase(
                    "empty",
                    "Empty",
                    "Explains an empty state and offers a clear next action.",
                    Empty(
                        EmptyHeader(
                            EmptyMedia("＋", variant="icon"),
                            EmptyTitle("No projects yet"),
                            EmptyDescription(
                                "Create your first project to start building with PyJS UI."
                            ),
                        ),
                        EmptyContent(Button("Create project")),
                    ),
                ),
                component_showcase(
                    "forms",
                    "Forms",
                    "Collects and validates user input using native, accessible form controls.",
                    CatalogForm(),
                    source_module="field",
                ),
                component_showcase(
                    "hover-card",
                    "Hover Card",
                    "Previews useful context when a link is hovered or receives keyboard focus.",
                    HoverCard(
                        HoverCardTrigger("@ada", href="#hover-card"),
                        HoverCardContent(
                            div(
                                tw("flex gap-4"),
                                Avatar(fallback="AL", alt="Ada Lovelace"),
                                div(
                                    h3(tw("font-semibold text-slate-950"), "Ada Lovelace"),
                                    p(
                                        tw("mt-1 text-sm leading-5 text-slate-600"),
                                        "Mathematician and author of the first published algorithm.",
                                    ),
                                ),
                            )
                        ),
                        align="start",
                    ),
                ),
                component_showcase(
                    "kbd",
                    "Kbd",
                    "Displays keyboard input and shortcut combinations.",
                    div(
                        tw("flex items-center gap-3 text-sm text-slate-600"),
                        "Open command menu",
                        KbdGroup(Kbd("Ctrl"), "+", Kbd("K")),
                    ),
                ),
                component_showcase(
                    "popover",
                    "Popover",
                    "Displays interactive content in a floating panel anchored to its trigger.",
                    Popover(
                        PopoverTrigger("Open settings"),
                        PopoverContent(
                            PopoverHeader(
                                PopoverTitle("Dimensions"),
                                PopoverDescription("Set the size for the workspace."),
                            ),
                            div(
                                tw("grid gap-2 text-sm"),
                                Label("Width", Input(placeholder="100%", name="width")),
                                Label("Height", Input(placeholder="320px", name="height")),
                            ),
                            PopoverClose("Done"),
                            label="Dimensions",
                        ),
                    ),
                ),
                component_showcase(
                    "progress",
                    "Progress",
                    "Displays completion for a task whose current value is known.",
                    div(
                        tw("grid max-w-lg gap-3"),
                        div(
                            tw("flex items-center justify-between text-sm"),
                            tag("span", tw("font-medium text-slate-950"), "Uploading files"),
                            tag("span", tw("text-slate-500"), "66%"),
                        ),
                        ProgressBar(66, "File upload progress"),
                    ),
                ),
                component_showcase(
                    "radio-group",
                    "Radio Group",
                    "Chooses one value from a visible set of mutually exclusive options.",
                    RadioGroup(
                        RadioGroupItem("default", "Default"),
                        RadioGroupItem("comfortable", "Comfortable", checked=True),
                        RadioGroupItem("compact", "Compact"),
                        name="catalog-density",
                    ),
                ),
                component_showcase(
                    "separator",
                    "Separator",
                    "Visually or semantically separates groups of related content.",
                    div(
                        tw("flex h-6 items-center gap-4 text-sm text-slate-700"),
                        "Overview",
                        Separator("vertical"),
                        "Components",
                        Separator("vertical", decorative=False),
                        "Examples",
                    ),
                ),
                component_showcase(
                    "sheet",
                    "Sheet",
                    "Extends a modal panel from an edge of the viewport for supporting tasks.",
                    Sheet(
                        SheetTrigger("Edit profile"),
                        SheetContent(
                            "Edit profile",
                            SheetHeader(
                                SheetTitle("Edit profile"),
                                SheetDescription(
                                    "Make changes here, then close the sheet when finished."
                                ),
                            ),
                            div(
                                tw("grid gap-4"),
                                Label(
                                    "Name",
                                    Input(placeholder="Ada Lovelace", name="sheet-name"),
                                ),
                                Label(
                                    "Username",
                                    Input(placeholder="@ada", name="sheet-username"),
                                ),
                            ),
                            SheetFooter(SheetClose("Save changes")),
                            side="right",
                        ),
                    ),
                ),
                component_showcase(
                    "skeleton",
                    "Skeleton",
                    "A placeholder that preserves layout while content is loading.",
                    div(
                        tw("flex max-w-md items-center gap-4"),
                        Skeleton("3rem", "3rem"),
                        div(
                            tw("grid flex-1 gap-2"),
                            Skeleton("75%", "0.875rem"),
                            Skeleton("100%", "0.875rem"),
                        ),
                    ),
                ),
                component_showcase(
                    "spinner",
                    "Spinner",
                    "Communicates that an indeterminate operation is in progress.",
                    div(
                        tw("flex items-center gap-4"),
                        Spinner(),
                        Button("Saving", variant="secondary"),
                    ),
                ),
                component_showcase(
                    "table",
                    "Table",
                    "A responsive collection of semantic elements for tabular data.",
                    Table(
                        TableCaption("A list of recent invoices."),
                        TableHeader(
                            TableRow(
                                TableHead("Invoice"),
                                TableHead("Status"),
                                TableHead("Amount"),
                            )
                        ),
                        TableBody(
                            TableRow(
                                TableCell("INV001"),
                                TableCell(Badge("Paid", variant="secondary")),
                                TableCell("$250.00"),
                            ),
                            TableRow(
                                TableCell("INV002"),
                                TableCell(Badge("Pending", variant="outline")),
                                TableCell("$150.00"),
                            ),
                            TableRow(
                                TableCell("INV003"),
                                TableCell(Badge("Paid", variant="secondary")),
                                TableCell("$350.00"),
                            ),
                        ),
                        TableFooter(
                            TableRow(
                                TableCell("Total"),
                                TableCell("3 invoices"),
                                TableCell("$750.00"),
                            )
                        ),
                    ),
                ),
                component_showcase(
                    "tabs",
                    "Tabs",
                    "Switches between related sections while showing one panel at a time.",
                    TabGroup(
                        Tab(
                            "account",
                            "Account",
                            h3(tw("font-medium text-slate-950"), "Account"),
                            p(
                                tw("mt-1 text-slate-600"),
                                "Update your name, email address, and profile details.",
                            ),
                        ),
                        Tab(
                            "password",
                            "Password",
                            h3(tw("font-medium text-slate-950"), "Password"),
                            p(
                                tw("mt-1 text-slate-600"),
                                "Choose a strong password you do not use elsewhere.",
                            ),
                        ),
                        Tab(
                            "notifications",
                            "Notifications",
                            h3(tw("font-medium text-slate-950"), "Notifications"),
                            p(
                                tw("mt-1 text-slate-600"),
                                "Decide which product updates should reach your inbox.",
                            ),
                        ),
                        default_value="account",
                    ),
                ),
                component_showcase(
                    "toggle",
                    "Toggle",
                    "A two-state button that keeps its pressed state on the DOM.",
                    div(
                        tw("flex items-center gap-2"),
                        Toggle("Bold", pressed=True),
                        Toggle("Italic", variant="outline"),
                    ),
                ),
                component_showcase(
                    "toggle-group",
                    "Toggle Group",
                    "Groups related toggles while optionally enforcing a single selection.",
                    ToggleGroup(
                        Toggle("Left", value="left"),
                        Toggle("Center", value="center", pressed=True),
                        Toggle("Right", value="right"),
                    ),
                    source_module="toggle",
                ),
                component_showcase(
                    "tooltip",
                    "Tooltip",
                    "Names or describes a control when it is hovered or receives keyboard focus.",
                    Tooltip(
                        TooltipTrigger("?"),
                        TooltipContent("Add this page to your library"),
                    ),
                ),
                remaining_component_showcases(),
                div(
                    tw("mt-16 scroll-mt-24 border-t border-slate-200 pt-12"),
                    {"id": "examples"},
                    h2(tw("text-2xl font-bold tracking-tight text-slate-950"), "Examples"),
                    p(
                        tw("mt-3 max-w-2xl text-slate-600"),
                        "Complete applications that exercise PyJS across web and native UI.",
                    ),
                    div(
                        tw("mt-7 grid gap-5 sm:grid-cols-2"),
                        example_card(
                            "Calculator",
                            "A server-rendered calculator that remembers its latest result.",
                            "python -m pyjs_examples.calculator",
                        ),
                        example_card(
                            "Project workspace",
                            "A launch dashboard combining navigation, tasks, forms, and overlays.",
                            "python -m pyjs_examples.components",
                        ),
                        example_card(
                            "Chat",
                            "Rooms, an assistant conversation, and workspace membership.",
                            "python -m pyjs_examples.chat",
                        ),
                        example_card(
                            "Store",
                            "A polished storefront with a cart and Stripe integration boundary.",
                            "python -m pyjs_examples.store",
                        ),
                        example_card(
                            "Space Invaders",
                            "A tested 3D arcade game rendered with WebGPU.",
                            "python -m pyjs_examples.space_invaders",
                        ),
                        example_card(
                            "Notes",
                            "A polished Google Keep-inspired native Android showcase.",
                            "python -m pyjs_examples.notes",
                        ),
                        example_card(
                            "Counter",
                            "The smallest reactive custom-element example.",
                            "python -m pyjs_examples.counter",
                        ),
                    ),
                ),
            ),
        )
        header = tag(
            "header",
            tw(
                "sticky top-0 z-40 flex h-[4.25rem] items-center border-b "
                "border-slate-200 bg-white/95 px-6 backdrop-blur"
            ),
            div(
                tw("mx-auto flex w-full max-w-7xl items-center justify-between"),
                div(
                    tw("flex items-center gap-3"),
                    a(
                        tw(
                            "flex items-center gap-2 text-base font-bold "
                            "tracking-tight text-slate-950"
                        ),
                        {"href": site_root},
                        tag(
                            "span",
                            tw(
                                "grid size-[1.9rem] place-items-center rounded-lg "
                                "bg-indigo-600 font-mono text-xs font-extrabold text-white"
                            ),
                            "Py",
                        ),
                        "PyJS",
                    ),
                    tag(
                        "span",
                        tw(
                            "hidden border-l border-slate-300 pl-3 text-sm "
                            "font-medium text-slate-500 sm:inline"
                        ),
                        "Components",
                    ),
                ),
                tag(
                    "nav",
                    tw("flex items-center gap-3 text-sm text-slate-500"),
                    {"aria-label": "PyJS website"},
                    a(
                        tw("hover:text-slate-950"),
                        {"href": site_root},
                        "Home",
                    ),
                    a(
                        tw("hover:text-slate-950"),
                        {"href": site_root + "docs/"},
                        "Docs",
                    ),
                    a(
                        tw("hidden font-semibold text-slate-950 sm:inline"),
                        {
                            "aria-current": "page",
                            "href": site_root + "components/",
                        },
                        "Components",
                    ),
                    a(
                        tw("hover:text-slate-950"),
                        {"href": site_root + "examples/"},
                        "Examples",
                    ),
                    a(
                        tw("hidden hover:text-slate-950 lg:inline"),
                        {"href": site_root + "why-pyjs/"},
                        "Why PyJS",
                    ),
                    a(
                        tw("hidden hover:text-slate-950 md:inline"),
                        {"href": "https://github.com/pyjs/pyjs"},
                        "GitHub",
                    ),
                    a(
                        tw("hidden hover:text-slate-950 xl:inline"),
                        {"href": "https://discord.gg/YktKpQPG7"},
                        "Discord",
                    ),
                    a(
                        tw("hidden hover:text-slate-950 xl:inline"),
                        {"href": "https://x.com/pyjsdev"},
                        "X",
                    ),
                ),
            ),
        )
        self.add(
            tw("block min-h-screen bg-slate-50 text-slate-950"),
            a(
                tw(
                    "fixed left-3 top-3 z-50 -translate-y-20 rounded-md bg-slate-950 "
                    "px-3 py-2 text-sm font-semibold text-white focus:translate-y-0"
                ),
                {"href": "#main-content"},
                "Skip to content",
            ),
            header,
            div(tw("mx-auto flex max-w-7xl"), sidebar, content),
        )

    def save_profile(self, event: Event):
        self.status.textContent = "Saved profile for " + self.name_input.value + "."
        self.dialog.close()


def main():
    return CatalogApp()
