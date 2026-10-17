from typing import cast

from pyjs import effect, js, state
from pyjs.server import (
    ApplicationPage,
    ApplicationSection,
    CursorPageRequest,
    LiveSession,
    OperationError,
    Page,
    Stream,
    StreamSnapshot,
    WatchedQuery,
)
from pyjs.web.crypto import crypto
from pyjs.web.dom import Element
from pyjs.web.domx import div, form, h1, input, p, ref, span, tag, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLButtonElement, HTMLInputElement, HTMLSelectElement
from pyjs.web.navigation import NavigationLayout
from pyjs.web.ui import Widget
from pyjs.web.ui.badge import Badge
from pyjs.web.ui.button import Button
from pyjs.web.ui.card import Card, CardContent, CardFooter
from pyjs.web.ui.chart import LineChart
from pyjs.web.ui.checkbox import Checkbox
from pyjs.web.ui.date import DateText
from pyjs.web.ui.empty import Empty, EmptyDescription, EmptyHeader, EmptyTitle
from pyjs.web.ui.infinite_scroll import InfiniteScroll
from pyjs.web.ui.item import Item, ItemActions, ItemContent, ItemGroup, ItemTitle
from pyjs.web.ui.model import IntegerModelField, ModelForm, TextModelField
from pyjs.web.ui.pagination import CursorPagination
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
from pyjs.web.ui.streaming_list import StreamingList
from pyjs.web.ui.streaming_log import StreamingLog
from pyjs.web.ui.theme import Theme, ThemeProvider

from .api import api
from .core import (
    AccountSummary,
    CatalogFilters,
    CheckoutDraft,
    CheckoutResult,
    InventoryChange,
    ModeratedReview,
    OrderSummary,
    Product,
    ProductSort,
    Review,
    ReviewDraft,
    ReviewStatus,
    TrafficSummary,
    VisitorDraft,
    VisitorEvent,
)


@js
def northstar_theme() -> Theme:
    return Theme(
        "northstar",
        background="#fafaf9",
        foreground="#1c1917",
        surface="#ffffff",
        surface_foreground="#1c1917",
        primary="#78350f",
        primary_hover="#92400e",
        primary_foreground="#fffbeb",
        muted="#f5f5f4",
        muted_foreground="#78716c",
        border="#d6d3d1",
        ring="#d97706",
        radius="0.75rem",
    )


@js
def northstar_account_theme() -> Theme:
    return Theme(
        "northstar-account",
        background="#0c0a09",
        foreground="#fafaf9",
        surface="#1c1917",
        surface_foreground="#fafaf9",
        primary="#fbbf24",
        primary_hover="#fcd34d",
        primary_foreground="#1c1917",
        muted="#292524",
        muted_foreground="#a8a29e",
        border="#44403c",
        ring="#fbbf24",
        radius="0.75rem",
    )


@js
class CheckoutForm(ModelForm[CheckoutDraft]):
    customer_name = TextModelField(label="Name")

    class Meta:
        fields = ("email",)


@js
class ReviewForm(ModelForm[ReviewDraft]):
    author_name = TextModelField(label="Your name")
    rating = IntegerModelField(label="Rating")
    body = TextModelField(label="Review")

    class Meta:
        fields = "__all__"


@js
def default_checkout() -> CheckoutDraft:
    return CheckoutDraft.model_validate(
        {"customer_name": "Ada Lovelace", "email": "ada@example.com"}
    )


@js
def default_review() -> ReviewDraft:
    return ReviewDraft()


@js
def money(cents: int) -> str:
    return "$" + str(cents // 100)


@js
def store_mark():
    return div(
        tw(
            "flex size-9 items-center justify-center rounded-full bg-stone-950 "
            "font-serif text-sm italic text-white"
        ),
        "N",
    )


@js
class StoreHeader(Widget):
    def __init__(self, cart: Sheet | None = None):
        super().__init__()
        self.mobile_links = ref(
            div(
                tw("hidden border-t border-stone-200 px-5 py-4 md:hidden"),
                tag("a", tw("mr-5"), {"href": "/"}, "Shop"),
                        tag("a", tw("mr-5"), {"href": "/story/"}, "Our story"),
                        tag("a", {"href": "/account/"}, "Account"),
            )
        )
        self.menu = ref(Button("Menu", variant="ghost", size="sm"))
        self.menu.setAttribute("aria-expanded", "false")
        self.menu.on_click(self.toggle_menu)
        actions = div(
            tw("ml-auto flex items-center gap-2"),
            div(tw("md:hidden"), self.menu),
        )
        if cart is not None:
            actions.append(cart)
        self.add(
            tw(
                "sticky top-0 z-30 block border-b border-stone-200/80 "
                "bg-stone-50/90 backdrop-blur-xl"
            ),
            tag(
                "header",
                div(
                    tw(
                        "mx-auto flex h-16 max-w-7xl items-center gap-8 "
                        "px-5 lg:px-8"
                    ),
                    tag(
                        "a",
                        tw("flex items-center gap-3 text-stone-950"),
                        {"href": "/", "aria-label": "Northstar home"},
                        store_mark(),
                        span(
                            tw("font-serif text-xl font-semibold tracking-tight"),
                            "Northstar",
                        ),
                    ),
                    tag(
                        "nav",
                        tw(
                            "hidden items-center gap-6 text-sm text-stone-600 "
                            "md:flex"
                        ),
                        {"aria-label": "Primary navigation"},
                        tag("a", {"href": "/"}, "Shop"),
                        tag("a", {"href": "/story/"}, "Our story"),
                        tag("a", {"href": "/account/"}, "Account"),
                    ),
                    actions,
                ),
            ),
            self.mobile_links,
        )

    def toggle_menu(self, event: Event):
        is_open = self.menu.getAttribute("aria-expanded") == "true"
        self.menu.setAttribute("aria-expanded", str(not is_open).lower())
        if is_open:
            self.mobile_links.classList.add("hidden")
        else:
            self.mobile_links.classList.remove("hidden")


@js
def hero_view():
    return tag(
        "section",
        tw("overflow-hidden border-b border-stone-200 bg-[#e8e1d5]"),
        div(
            tw(
                "mx-auto grid min-h-[33rem] max-w-7xl items-center gap-10 px-5 py-16 "
                "lg:grid-cols-[1.05fr_.95fr] lg:px-8"
            ),
            div(
                tw("relative z-10 max-w-2xl"),
                Badge("Autumn collection · 2026", variant="outline"),
                h1(
                    tw(
                        "mt-6 text-balance font-serif text-5xl font-medium leading-[0.98] "
                        "tracking-[-0.04em] text-stone-950 sm:text-7xl"
                    ),
                    "Objects for a quieter kind of work.",
                ),
                p(
                    tw("mt-6 max-w-xl text-pretty text-lg leading-8 text-stone-600"),
                    "Useful things, considered carefully. Designed for daily rituals and "
                    "made to become better with time.",
                ),
                tag(
                    "a",
                    tw(
                        "mt-8 inline-flex h-11 items-center rounded-full bg-stone-950 "
                        "px-6 text-sm font-medium text-white hover:bg-stone-800"
                    ),
                    {"href": "#collection"},
                    "Explore the collection",
                ),
            ),
            div(
                tw(
                    "relative mx-auto flex aspect-square w-full max-w-lg items-center "
                    "justify-center rounded-full bg-[#d3c5b1]"
                ),
                div(
                    tw(
                        "absolute left-[17%] top-[20%] h-[58%] w-[44%] rotate-[-8deg] "
                        "rounded-[2rem] bg-stone-900 shadow-2xl shadow-stone-900/30"
                    ),
                    div(
                        tw(
                            "absolute inset-x-5 top-7 h-2 rounded-full bg-stone-700"
                        )
                    ),
                    div(
                        tw(
                            "absolute inset-x-5 bottom-7 top-14 rounded-2xl "
                            "bg-[#dfd2bf] p-5 font-serif text-2xl italic text-stone-800"
                        ),
                        "Make space for good ideas.",
                    ),
                ),
                div(
                    tw(
                        "absolute bottom-[15%] right-[11%] flex size-40 rotate-[9deg] "
                        "items-center justify-center rounded-full border-[1.2rem] "
                        "border-[#8d7257] bg-[#c9ad8a] text-4xl shadow-xl"
                    ),
                    "☕",
                ),
            ),
        ),
    )


@js
def product_visual(symbol: str, tone: str):
    if tone == "clay":
        style = tw(
            "flex h-56 items-center justify-center overflow-hidden rounded-t-xl "
            "bg-[#d9b89c] text-7xl text-[#694b36] transition-transform duration-300 "
            "group-hover:scale-[1.015]"
        )
    elif tone == "moss":
        style = tw(
            "flex h-56 items-center justify-center overflow-hidden rounded-t-xl "
            "bg-[#b7c1a6] text-7xl text-[#3e4d35] transition-transform duration-300 "
            "group-hover:scale-[1.015]"
        )
    elif tone == "ink":
        style = tw(
            "flex h-56 items-center justify-center overflow-hidden rounded-t-xl "
            "bg-[#b9bcc4] text-7xl text-[#30343d] transition-transform duration-300 "
            "group-hover:scale-[1.015]"
        )
    else:
        style = tw(
            "flex h-56 items-center justify-center overflow-hidden rounded-t-xl "
            "bg-[#d7c7a7] text-7xl text-[#5b4a31] transition-transform duration-300 "
            "group-hover:scale-[1.015]"
        )
    return div(
        style,
        {"aria-hidden": "true", "data-slot": "product-media"},
        symbol,
    )


@js
def product_card(product: Product):
    add_button = Button("Add to bag", variant="outline")
    add_button.setAttribute("data-product", product.name)
    add_button.setAttribute("data-product-id", str(product.id))
    add_button.setAttribute("data-price", str(product.cents))
    if product.inventory == 0:
        # Button can also wrap an anchor; this instance has no href.
        cast(HTMLButtonElement, add_button.element).disabled = True
        add_button.element.textContent = "Sold out"
    details_button = Button("Reviews & ideas", variant="ghost")
    details_button.setAttribute("data-product-details", str(product.id))
    return Card(
        tw("group overflow-hidden border-stone-200 bg-stone-50 py-0 shadow-none"),
        {
            "data-inventory": str(product.inventory),
            "data-product-card": product.name,
            "data-product-id": str(product.id),
            "data-resource-identity": api.products.identity(product.id),
        },
        product_visual(product.symbol, product.tone),
        CardContent(
            div(
                tw("flex items-start justify-between gap-4 pt-5"),
                div(
                    tag(
                        "h3",
                        tw("font-serif text-xl font-medium text-stone-950"),
                        product.name,
                    ),
                    p(
                        tw("mt-1 text-sm leading-6 text-stone-500"),
                        product.description,
                    ),
                ),
                span(
                    tw("shrink-0 text-sm font-semibold text-stone-900"),
                    money(product.cents),
                ),
            )
        ),
        CardFooter(
            tw("flex items-center justify-between gap-2 pb-5"),
            add_button,
            details_button,
        ),
    )


@js
def cart_item_view(product_id: int, name: str, cents: int):
    item = Item(
        ItemContent(ItemTitle(name)),
        ItemActions(span(tw("font-medium text-stone-900"), money(cents))),
        variant="outline",
    )
    item.setAttribute("data-cart-item", name)
    item.setAttribute("data-product-id", str(product_id))
    return item


@js
def product_grid(products: list[Product]):
    cards: list[Element] = []
    for product in products:
        cards.append(product_card(product))
    if not cards:
        cards.append(
            Empty(
                tw("col-span-full border-stone-300"),
                EmptyHeader(
                    EmptyTitle("No products found"),
                    EmptyDescription(
                        "Try a broader search or include sold-out products."
                    ),
                ),
            )
        )
    return div(
        tw("mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4"),
        {"data-testid": "product-grid"},
        *cards,
    )


@js
def review_view(review: Review) -> Element:
    return div(
        tw("border-b border-stone-200 py-4 last:border-0"),
        div(
            tw("flex items-center justify-between gap-4"),
            p(tw("font-medium text-stone-900"), review.author_name),
            Badge(str(review.rating) + " / 5", variant="outline"),
        ),
        p(tw("mt-2 text-sm leading-6 text-stone-600"), review.body),
    )


@js
def recommendation_view(product: Product) -> Element:
    return div(
        tw("rounded-lg border border-stone-200 bg-white p-4"),
        div(
            tw("flex items-center justify-between gap-4"),
            p(tw("font-medium text-stone-900"), product.name),
            span(tw("text-sm font-semibold text-stone-700"), money(product.cents)),
        ),
        p(tw("mt-1 text-sm leading-6 text-stone-500"), product.description),
    )


@js
def review_rows_view(reviews: list[Review]) -> Element:
    review_rows: list[Element] = []
    for review in reviews:
        review_rows.append(review_view(review))
    if not review_rows:
        review_rows.append(p(tw("py-4 text-sm text-stone-500"), "No reviews yet."))
    return div({"data-review-rows": ""}, *review_rows)


@js
def reviews_panel(
    product: Product,
    reviews: list[Review],
    rows: Element,
    browse: Button,
    pagination: CursorPagination,
) -> Element:
    rating = 0
    for review in reviews:
        rating += review.rating

    summary = "No ratings yet"
    if reviews:
        summary = str(rating / len(reviews)) + " average from recent reviews"
    return div(
        div(
            tw("flex items-end justify-between gap-4"),
            div(
                p(
                    tw(
                        "text-xs font-semibold uppercase tracking-[0.16em] "
                        "text-stone-500"
                    ),
                    "Recent reviews",
                ),
                tag(
                    "h3",
                    tw("mt-1 font-serif text-3xl text-stone-950"),
                    product.name,
                ),
            ),
            p(tw("text-sm text-stone-500"), summary),
        ),
        div(tw("mt-4"), rows),
        div(
            tw("mt-4 flex flex-wrap items-center justify-between gap-3"),
            browse,
            pagination,
        ),
    )


@js
def recommendations_panel(recommendations: list[Product]) -> Element:
    recommendation_rows: list[Element] = []
    for recommendation in recommendations:
        recommendation_rows.append(recommendation_view(recommendation))
    if not recommendation_rows:
        recommendation_rows.append(
            p(tw("text-sm text-stone-500"), "No recommendations available.")
        )
    return div(
        p(
            tw(
                "text-xs font-semibold uppercase tracking-[0.16em] "
                "text-stone-500"
            ),
            "Pairs well with",
        ),
        div(tw("mt-4 grid gap-3"), *recommendation_rows),
    )


@js
def review_submission_panel(form: ReviewForm, notice: Element) -> Element:
    submit = Button("Submit for review")
    submit.setAttribute("type", "submit")
    form.element.append(notice, submit.element)
    return div(
        tw("border-t border-stone-200 pt-6 lg:col-span-2"),
        p(
            tw(
                "text-xs font-semibold uppercase tracking-[0.16em] "
                "text-stone-500"
            ),
            "Share your experience",
        ),
        p(
            tw("mt-2 max-w-2xl text-sm leading-6 text-stone-500"),
            "Reviews appear publicly after a store moderator approves them.",
        ),
        div(tw("mt-5 max-w-xl"), form),
    )


@js
class ProductInsights(Widget):
    def __init__(
        self,
        product: Product,
        reviews: list[Review],
        recommendations: list[Product],
    ):
        super().__init__()
        self.set_data("product-id", str(product.id))
        self.review_rows = ref(review_rows_view(reviews))
        self.review_pagination = ref(
            CursorPagination(label="Product review pagination", size=2)
        )
        self.review_pagination.previous.setAttribute(
            "data-testid", "review-previous"
        )
        self.review_pagination.next.setAttribute("data-testid", "review-next")
        self.review_pagination.on_page(self.load_review_page)
        self.browse_reviews = ref(Button("Browse all reviews", variant="outline"))
        self.browse_reviews.setAttribute("data-testid", "browse-reviews")
        self.browse_reviews.on_click(self.browse_all_reviews)
        self.review_form = ref(ReviewForm(default_review()))
        self.review_form.setAttribute("data-testid", "review-form")
        self.review_form.get_control("rating").setAttribute("min", "1")
        self.review_form.get_control("rating").setAttribute("max", "5")
        self.review_form.element.addEventListener("submit", self.submit_review)
        self.review_notice = ref(
            p(
                tw("min-h-5 text-sm text-stone-500"),
                {"aria-live": "polite", "data-testid": "review-notice"},
            )
        )
        self.add(
            tw("block"),
            {"data-product-insights": product.name},
            Card(
                tw("mt-8 border-stone-200 bg-stone-100 shadow-none"),
                CardContent(
                    tw("grid gap-8 pt-6 lg:grid-cols-[1.1fr_.9fr]"),
                    reviews_panel(
                        product,
                        reviews,
                        self.review_rows,
                        self.browse_reviews,
                        self.review_pagination,
                    ),
                    recommendations_panel(recommendations),
                    review_submission_panel(
                        self.review_form,
                        self.review_notice,
                    ),
                ),
            ),
        )

    def product_id(self) -> int:
        value = self.get_data("product-id")
        if value is None:
            raise ValueError("Product insights are missing their product ID.")
        return int(value)

    async def browse_all_reviews(self, event: Event):
        await self.load_review_page(CursorPageRequest(size=2))

    async def load_review_page(self, request: CursorPageRequest):
        page = await api.products.reviews.list(self.product_id(), request)
        updated = review_rows_view(page.items)
        self.review_rows.replaceChildren(*updated.children)
        self.review_pagination.set_page(page)

    async def submit_review(self, event: Event):
        event.preventDefault()
        self.review_form.clear_errors()
        draft = self.review_form.read_model()
        try:
            await api.products.reviews.submit(self.product_id(), draft)
        except OperationError as error:
            self.review_form.set_errors(error, "draft")
            return
        self.review_form.set_model(default_review())
        self.review_notice.textContent = "Thanks. Your review is awaiting approval."


@js
def search_input_view():
    return input(
        tw(
            "h-10 min-w-0 flex-1 rounded-full border border-stone-300 bg-white "
            "px-4 text-sm outline-none placeholder:text-stone-400 "
            "focus:border-stone-600 focus:ring-2 focus:ring-stone-200"
        ),
        {
            "aria-label": "Search the collection",
            "data-testid": "catalog-search",
            "placeholder": "Search products",
            "type": "search",
        },
    )


@js
def sort_select_view() -> HTMLSelectElement:
    return cast(
        HTMLSelectElement,
        tag(
            "select",
            tw(
                "h-10 rounded-full border border-stone-300 bg-white px-4 pr-9 "
                "text-sm text-stone-700 outline-none focus:border-stone-600 "
                "focus:ring-2 focus:ring-stone-200"
            ),
            {
                "aria-label": "Sort products",
                "data-testid": "catalog-sort",
            },
            tag("option", {"value": "featured"}, "Featured"),
            tag("option", {"value": "name"}, "Name"),
            tag("option", {"value": "price-ascending"}, "Price: low to high"),
            tag("option", {"value": "price-descending"}, "Price: high to low"),
        ),
    )


@js
def search_form_view(
    search_input: Element,
    sort_select: HTMLSelectElement,
    available_filter: Checkbox,
    status: Element,
):
    submit = Button("Search", variant="outline")
    submit.setAttribute("type", "submit")
    return form(
        tw(
            "mt-8 grid w-full gap-3 md:grid-cols-[minmax(14rem,1fr)_auto_auto_auto] "
            "md:items-center"
        ),
        {"data-testid": "catalog-search-form", "role": "search"},
        search_input,
        sort_select,
        tag(
            "label",
            tw(
                "flex h-10 cursor-pointer items-center gap-2 rounded-full border "
                "border-stone-300 bg-white px-4 text-sm text-stone-700"
            ),
            available_filter,
            "In stock only",
        ),
        submit,
        status,
    )


@js
def pagination_view(pagination: CursorPagination):
    return tag(
        "nav",
        tw("mt-8 flex items-center justify-end gap-2"),
        {"aria-label": "Catalog pages"},
        pagination,
    )


@js
def collection_view(
    search: Element,
    grid: Element,
    insights: Element,
    pagination: Element,
):
    return tag(
        "section",
        tw("mx-auto max-w-7xl px-5 py-20 lg:px-8"),
        {"id": "collection"},
        div(
            tw("flex flex-col justify-between gap-4 sm:flex-row sm:items-end"),
            div(
                tag(
                    "p",
                    tw("text-xs font-semibold uppercase tracking-[0.18em] text-stone-500"),
                    "The collection",
                ),
                tag(
                    "h2",
                    tw("mt-2 font-serif text-4xl font-medium tracking-tight text-stone-950"),
                    "Everyday, elevated",
                ),
            ),
            p(
                tw("max-w-md text-sm leading-6 text-stone-500"),
                "Small-batch objects selected for usefulness, honest materials, and a "
                "long life at home or work.",
            ),
        ),
        search,
        grid,
        insights,
        pagination,
    )


@js
def store_footer():
    return tag(
        "footer",
        tw("border-t border-stone-200 bg-white"),
        {"id": "story"},
        div(
            tw(
                "mx-auto flex max-w-7xl flex-col gap-4 px-5 py-10 text-sm text-stone-500 "
                "sm:flex-row sm:items-center sm:justify-between lg:px-8"
            ),
            div(
                tw("flex items-center gap-3 text-stone-950"),
                store_mark(),
                "Northstar Supply",
            ),
            p("A complete commerce flow written in Python and rendered by PyJS."),
        ),
    )


@js
class CatalogPage(Widget):
    live_session: LiveSession
    catalog_query: WatchedQuery[Page[Product]]
    cart_count = state(0)
    cart_total = state(0)
    checkout_state = state("ready")

    def __init__(self, page: Page[Product]):
        super().__init__()
        self.cart_count = 0
        self.cart_total = 0
        self.checkout_state = "ready"

        self.cart_items = ref(ItemGroup())
        self.empty_cart = ref(
            div(
                tw("rounded-xl border border-dashed border-stone-300 p-8 text-center"),
                tag("p", tw("font-medium text-stone-900"), "Your bag is empty"),
                p(tw("mt-1 text-sm text-stone-500"), "Add something made to last."),
            )
        )
        self.cart_items.append(self.empty_cart)
        self.cart_count_label = ref(span("0 items"))
        self.cart_total_label = ref(span("$0"))
        self.checkout_notice = ref(
            p(
                tw("min-h-5 text-xs leading-5 text-stone-500"),
                {"aria-live": "polite", "data-testid": "checkout-notice"},
            )
        )
        self.checkout_link = ref(
            tag(
                "a",
                tw(
                    "hidden h-10 items-center justify-center rounded-md bg-amber-400 "
                    "px-4 text-sm font-medium text-stone-950 hover:bg-amber-300"
                ),
                {"data-testid": "payment-link"},
                "Continue to test payment",
            )
        )
        self.clear_button = ref(Button("Clear", variant="ghost", size="sm"))
        self.clear_button.setAttribute("data-testid", "clear-cart")
        self.clear_button.on_click(self.clear_cart)
        self.checkout_form = ref(CheckoutForm(default_checkout()))
        self.checkout_form.setAttribute("data-testid", "checkout-form")
        self.checkout_button = ref(Button("Place order", size="lg"))
        self.checkout_button.setAttribute("data-testid", "checkout")
        self.checkout_button.on_click(self.checkout)
        self.cart_sheet = ref(
            Sheet(
                SheetTrigger("Bag · 0"),
                SheetContent(
                    "Shopping bag",
                    SheetHeader(
                        SheetTitle("Shopping bag"),
                        SheetDescription(
                            "Review your selection before continuing to secure checkout."
                        ),
                    ),
                    div(
                        tw("min-h-0 flex-1 overflow-y-auto"),
                        self.cart_items,
                    ),
                    div(
                        tw("mt-auto grid gap-4"),
                        Separator(),
                        self.checkout_form,
                        div(
                            tw("flex items-center justify-between text-sm"),
                            div(
                                tw("flex items-center gap-2"),
                                self.cart_count_label,
                                self.clear_button,
                            ),
                            div(
                                span(tw("mr-2 text-stone-500"), "Subtotal"),
                                self.cart_total_label,
                            ),
                        ),
                        self.checkout_notice,
                        self.checkout_link,
                    ),
                    SheetFooter(
                        SheetClose("Keep shopping"),
                        self.checkout_button,
                    ),
                    side="right",
                ),
            )
        )
        self.cart_sheet.trigger.setAttribute("data-testid", "cart-trigger")
        self.search_input = ref(search_input_view())
        self.sort_select = ref(sort_select_view())
        self.sort_select.addEventListener("change", self.filter_catalog)
        self.available_filter = ref(Checkbox(name="available_only"))
        self.available_filter.setAttribute("data-testid", "catalog-available")
        self.available_filter.on_change(self.filter_catalog)
        self.search_status = ref(
            p(
                tw("text-xs text-stone-500 md:col-span-4"),
                {"aria-live": "polite", "data-testid": "catalog-search-status"},
                self.catalog_status(page),
            )
        )
        self.search_form = ref(
            search_form_view(
                self.search_input,
                self.sort_select,
                self.available_filter,
                self.search_status,
            )
        )
        self.search_form.addEventListener("submit", self.search_catalog)
        self.product_grid = ref(product_grid(page.items))
        self.product_insights = ref(
            div(
                tw("hidden"),
                {"aria-live": "polite", "data-testid": "product-insights"},
            )
        )
        self.pagination = ref(
            CursorPagination(
                page.previous,
                page.next,
                label="Catalog pagination",
                size=2,
            )
        )
        self.pagination.previous.setAttribute("data-testid", "catalog-previous")
        self.pagination.next.setAttribute("data-testid", "catalog-next")
        self.pagination.on_page(self.load_catalog_page)

        self.add(
            tw("block min-h-screen bg-stone-50 font-sans text-stone-950"),
            {"data-testid": "store"},
            StoreHeader(self.cart_sheet),
            tag(
                "main",
                hero_view(),
                collection_view(
                    self.search_form,
                    self.product_grid,
                    self.product_insights,
                    pagination_view(self.pagination),
                ),
            ),
            store_footer(),
        )
        self.addEventListener("click", self.clicked)

    @effect(cart_count)
    def render_cart_count(self):
        label = str(self.cart_count) + (" item" if self.cart_count == 1 else " items")
        self.cart_count_label.textContent = label
        self.cart_sheet.trigger.element.textContent = "Bag · " + str(self.cart_count)

    @effect(cart_total)
    def render_cart_total(self):
        self.cart_total_label.textContent = money(self.cart_total)

    @effect(checkout_state)
    def render_checkout_state(self):
        if self.checkout_state == "empty":
            self.checkout_notice.textContent = "Add an item before continuing to checkout."
        elif self.checkout_state == "ready-for-payment":
            self.checkout_notice.textContent = (
                "Order ready. Continue to secure payment."
            )
        else:
            self.checkout_notice.textContent = ""
            self.checkout_link.classList.add("hidden")
            self.checkout_link.classList.remove("inline-flex")

    def initialize(self):
        self.live_session = api.live_session()
        self.catalog_query = (
            WatchedQuery(
                api.products.list,
                CatalogFilters(),
                CursorPageRequest(size=2),
            )
            .on_update(self.set_catalog)
            .watch(self.live_session)
        )

    def reconnected(self):
        self.live_session.start()

    def disconnected(self):
        self.live_session.close()

    def catalog_status(self, page: Page[Product]) -> str:
        count = len(page.items)
        total = count if page.total is None else page.total
        label = "product" if total == 1 else "products"
        if count == total:
            return str(total) + " " + label
        return str(count) + " of " + str(total) + " " + label

    def set_catalog(self, page: Page[Product]):
        updated = product_grid(page.items)
        self.product_grid.replaceChildren(*updated.children)
        self.search_status.textContent = self.catalog_status(page)
        self.pagination.set_page(page)

    def clear_product_insights(self):
        self.product_insights.replaceChildren()
        self.product_insights.classList.add("hidden")

    async def load_catalog_page(self, page: CursorPageRequest):
        self.clear_product_insights()
        self.search_status.textContent = "Loading…"
        sort = cast(ProductSort, self.sort_select.value)
        self.catalog_query.set_args(
            CatalogFilters(
                search=self.search_input.value.strip(),
                sort=sort,
                available_only=self.available_filter.is_checked(),
            ),
            page,
        )
        try:
            await self.catalog_query.reload()
        except Exception:
            self.search_status.textContent = "The catalog could not be loaded."

    async def search_catalog(self, event: Event):
        event.preventDefault()
        await self.load_catalog_page(CursorPageRequest(size=2))

    async def filter_catalog(self, event: Event):
        await self.load_catalog_page(CursorPageRequest(size=2))

    def add_product(self, product_id: int, name: str, cents: int):
        self.removeAttribute("data-checkout-key")
        if self.cart_count == 0:
            self.cart_items.replaceChildren()
        self.cart_items.append(cart_item_view(product_id, name, cents))
        self.cart_count += 1
        self.cart_total += cents
        self.checkout_state = "ready"

    async def clicked(self, event: Event):
        target = cast(Element, event.target)
        details = target.closest("[data-product-details]")
        if details is not None:
            product_id = details.getAttribute("data-product-details")
            if product_id is not None:
                await self.load_product_details(int(product_id))
            return
        product = target.closest("[data-product]")
        if product is None:
            return
        name = product.getAttribute("data-product")
        product_id = product.getAttribute("data-product-id")
        price = product.getAttribute("data-price")
        if name is not None and product_id is not None and price is not None:
            self.add_product(int(product_id), name, int(price))

    async def load_product_details(self, product_id: int):
        self.product_insights.classList.remove("hidden")
        self.product_insights.replaceChildren(
            p(tw("py-6 text-sm text-stone-500"), "Loading reviews…")
        )
        product = await api.products.get(product_id)
        if product is None:
            self.product_insights.replaceChildren(
                p(tw("py-6 text-sm text-red-700"), "This product is unavailable.")
            )
            return
        reviews = api.products.related(product, api.products.reviews)
        recommendations = api.products.related(
            product,
            api.products.recommendations,
        )
        if reviews is None or recommendations is None:
            self.product_insights.replaceChildren(
                p(
                    tw("py-6 text-sm text-red-700"),
                    "Product insights could not be loaded.",
                )
            )
            return
        self.product_insights.replaceChildren(
            ProductInsights(product, reviews, recommendations)
        )

    def clear_cart(self, event: Event):
        self.removeAttribute("data-checkout-key")
        self.cart_items.replaceChildren(self.empty_cart)
        self.cart_count = 0
        self.cart_total = 0
        self.checkout_state = "ready"

    def product_ids(self) -> list[int]:
        values: list[int] = []
        for item in self.cart_items.children:
            product_id = item.getAttribute("data-product-id")
            if product_id is not None:
                values.append(int(product_id))
        return values

    def checkout_key(self) -> str:
        value = self.getAttribute("data-checkout-key")
        if value is None:
            value = crypto.randomUUID()
            self.setAttribute("data-checkout-key", value)
        return value

    async def checkout(self, event: Event):
        if self.cart_count == 0:
            self.checkout_state = "empty"
            return
        self.checkout_form.clear_errors()
        draft = self.checkout_form.read_model()
        try:
            result = await api.orders.checkout(
                draft,
                self.product_ids(),
                self.checkout_key(),
            )
        except OperationError as error:
            self.checkout_form.set_errors(error, "draft")
            self.checkout_notice.textContent = error.issues[0].detail
            return
        self.complete_checkout(result)

    def complete_checkout(self, result: CheckoutResult):
        self.removeAttribute("data-checkout-key")
        receipt = result.receipt
        self.checkout_state = "ready-for-payment"
        self.checkout_notice.textContent = (
            "Order #" + str(receipt.id) + " is ready for secure payment."
        )
        self.checkout_link.setAttribute("href", result.checkout_url)
        self.checkout_link.classList.remove("hidden")
        self.checkout_link.classList.add("inline-flex")
        self.cart_items.replaceChildren(self.empty_cart)
        self.cart_count = 0
        self.cart_total = 0


@js
def public_page(content: Element) -> Element:
    return div(
        tw("min-h-screen bg-stone-50 font-sans text-stone-950"),
        StoreHeader(),
        tag("main", content),
        store_footer(),
    )


@js
def story_page() -> Element:
    return public_page(
        tag(
            "article",
            tw("mx-auto max-w-3xl px-5 py-24 lg:px-8"),
            store_mark(),
            h1(
                tw("mt-8 font-serif text-5xl tracking-tight text-stone-950"),
                "Useful things, considered carefully.",
            ),
            p(
                tw("mt-8 text-lg leading-8 text-stone-600"),
                "Northstar Supply is a static, server-rendered page. It shares "
                "the public Store bundle and stylesheet, but ships no page-specific "
                "JavaScript.",
            ),
            tag(
                "a",
                tw(
                    "mt-10 inline-flex rounded-full bg-stone-950 px-6 py-3 "
                    "text-sm font-medium text-white"
                ),
                {"href": "/"},
                "Return to the collection",
            ),
        )
    )


@js
def order_history_rows(page: Page[OrderSummary]) -> list[Element]:
    if not page.items:
        return [
            Empty(
                EmptyHeader(
                    EmptyTitle("No orders yet"),
                    EmptyDescription("Completed checkouts will appear here."),
                )
            )
        ]
    rows: list[Element] = []
    for order in page.items:
        rows.append(
            div(
                tw(
                    "grid gap-2 border-b border-stone-800 py-4 last:border-0 "
                    "sm:grid-cols-[1fr_auto_auto] sm:items-center sm:gap-6"
                ),
                div(
                    p(tw("font-medium text-stone-100"), "Order #" + str(order.id)),
                    div(
                        tw("flex items-center gap-2 text-sm text-stone-400"),
                        DateText(order.placed_on),
                        span("·"),
                        span(order.status),
                    ),
                ),
                p(
                    tw("text-sm text-stone-300"),
                    str(order.item_count)
                    + (" item" if order.item_count == 1 else " items"),
                ),
                p(tw("font-medium text-stone-100"), money(order.total_cents)),
            )
        )
    return rows


@js
class AccountDashboard(Widget):
    live_session: LiveSession
    summary_query: WatchedQuery[AccountSummary]

    def __init__(self, summary: AccountSummary, orders: Page[OrderSummary]):
        super().__init__()
        self.set_data("account-id", str(summary.id))
        self.set_data("order-count", str(summary.order_count))
        self.set_data("total-cents", str(summary.total_cents))
        self.order_count = ref(span(str(summary.order_count)))
        self.total = ref(span(money(summary.total_cents)))
        self.order_history = ref(div(*order_history_rows(orders)))
        self.order_history.setAttribute("data-testid", "order-history")
        self.pagination = ref(
            CursorPagination(
                orders.previous,
                orders.next,
                label="Order history pagination",
                size=5,
            )
        )
        self.pagination.on_page(self.load_orders)
        self.add(
            tw("block min-h-screen bg-stone-950 px-5 py-20 text-stone-50 lg:px-8"),
            div(
                tw("mx-auto max-w-5xl"),
                tag(
                    "a",
                    tw("text-sm text-stone-300 hover:text-white"),
                    {"href": "/"},
                    "← Storefront",
                ),
                h1(tw("mt-8 font-serif text-5xl"), "Account overview"),
                p(
                    tw("mt-3 max-w-2xl text-stone-400"),
                    "This page owns a separate client API branch and refreshes "
                    "its typed summary after hydration.",
                ),
                tag(
                    "a",
                    tw(
                        "mt-6 inline-flex rounded-md border border-stone-700 px-3 "
                        "py-2 text-sm font-medium text-stone-200 hover:bg-stone-900"
                    ),
                    {"href": "/account/inventory/"},
                    "Manage inventory",
                ),
                tag(
                    "a",
                    tw(
                        "ml-3 mt-6 inline-flex rounded-md border border-stone-700 "
                        "px-3 py-2 text-sm font-medium text-stone-200 "
                        "hover:bg-stone-900"
                    ),
                    {"href": "/account/reviews/"},
                    "Moderate reviews",
                ),
                tag(
                    "a",
                    tw(
                        "ml-3 mt-6 inline-flex rounded-md border border-stone-700 "
                        "px-3 py-2 text-sm font-medium text-stone-200 "
                        "hover:bg-stone-900"
                    ),
                    {"href": "/account/visitors/"},
                    "Visitor activity",
                ),
                div(
                    tw("mt-12 grid gap-5 sm:grid-cols-2"),
                    Card(
                        tw("border-stone-700 bg-stone-900 text-stone-50"),
                        CardContent(
                            p(tw("text-sm text-stone-400"), "Orders"),
                            self.order_count,
                        ),
                    ),
                    Card(
                        tw("border-stone-700 bg-stone-900 text-stone-50"),
                        CardContent(
                            p(tw("text-sm text-stone-400"), "Order value"),
                            self.total,
                        ),
                    ),
                ),
                div(
                    tw("mt-12 rounded-xl border border-stone-800 bg-stone-900 px-5"),
                    div(
                        tw(
                            "flex items-center justify-between border-b "
                            "border-stone-800 py-5"
                        ),
                        div(
                            p(tw("font-medium"), "Order history"),
                            p(tw("text-sm text-stone-400"), "Newest orders first"),
                        ),
                        self.pagination,
                    ),
                    self.order_history,
                ),
            ),
        )

    async def initialize(self):
        account_id = self.get_data("account-id")
        order_count = self.get_data("order-count")
        total_cents = self.get_data("total-cents")
        if account_id is None or order_count is None or total_cents is None:
            raise ValueError("Account summary state is missing from the DOM.")
        summary = AccountSummary(
            id=int(account_id),
            order_count=int(order_count),
            total_cents=int(total_cents),
        )
        self.live_session = api.live_session()
        self.summary_query = (
            WatchedQuery(api.account.summary)
            .seed(summary)
            .on_update(self.set_summary)
            .watch(self.live_session, "orders")
        )

    def reconnected(self):
        self.live_session.start()

    def disconnected(self):
        self.live_session.close()

    async def load_orders(self, page: CursorPageRequest):
        orders = await api.account.history.list(page)
        self.order_history.replaceChildren(*order_history_rows(orders))
        self.pagination.set_page(orders)

    def set_summary(self, summary: AccountSummary):
        self.order_count.textContent = str(summary.order_count)
        self.total.textContent = money(summary.total_cents)


@js
def visitor_event_rows(events: list[VisitorEvent]) -> list[Element]:
    rows: list[Element] = []
    for visit in events:
        rows.append(
            tag(
                "article",
                tw(
                    "grid gap-3 border-b border-stone-800 px-5 py-4 last:border-0 "
                    "sm:grid-cols-[minmax(8rem,1fr)_minmax(7rem,auto)_auto] "
                    "sm:items-center sm:gap-6"
                ),
                {"data-visitor-event": str(visit.id)},
                div(
                    p(tw("font-medium text-stone-100"), visit.path),
                    p(
                        tw("mt-1 text-sm text-stone-400"),
                        visit.source + " · " + visit.device,
                    ),
                ),
                p(tw("text-sm text-stone-300"), visit.region),
                p(
                    tw("text-sm tabular-nums text-stone-400"),
                    DateText(visit.occurred_on),
                    " · " + visit.occurred_time,
                ),
            )
        )
    return rows


@js
def visitor_log_lines(events: list[VisitorEvent]) -> list[str]:
    lines: list[str] = []
    for visit in events:
        lines.append(
            visit.occurred_time
            + "  "
            + visit.path
            + "  "
            + visit.region
            + "  "
            + visit.device
        )
    lines.reverse()
    return lines


@js
class VisitorActivityPage(Widget):
    def __init__(
        self,
        summary: TrafficSummary,
        snapshot: StreamSnapshot[Page[VisitorEvent]],
    ):
        super().__init__()
        page = snapshot.value
        self.set_data("stream-sequence", str(snapshot.sequence))
        self.chart = ref(
            LineChart(
                summary.values,
                summary.labels,
                color="#fbbf24",
                grid_color="#44403c",
                label="Daily storefront visits",
            )
        )
        self.events = ref(
            StreamingList(
                *visitor_event_rows(page.items),
                label="Recent visitor activity",
                max_items=200,
                newest_first=True,
            )
        )
        tag(
            self.events,
            tw("h-[30rem] [&_[data-slot=message-scroller-content]]:gap-0"),
            {"data-testid": "visitor-events"},
        )
        self.log = ref(
            StreamingLog(
                *visitor_log_lines(page.items),
                label="Raw visitor request log",
                max_lines=200,
            )
        )
        tag(self.log, tw("h-64"), {"data-testid": "visitor-log"})
        self.more = ref(
            InfiniteScroll(
                page.next,
                label="Load older visits",
                size=4,
            )
        )
        self.more.on_load(self.load_more)
        self.simulate = ref(Button("Simulate live visit", variant="outline"))
        self.simulate.setAttribute("data-testid", "simulate-visitor")
        self.simulate.on_click(self.simulate_visit)
        self.live: Stream[VisitorEvent] | None = None
        self.add(
            tw("block min-h-screen bg-stone-950 px-5 py-16 text-stone-50 lg:px-8"),
            div(
                tw("mx-auto max-w-5xl"),
                tag(
                    "a",
                    tw("text-sm text-stone-300 hover:text-white"),
                    {"href": "/account/"},
                    "← Account",
                ),
                h1(tw("mt-8 font-serif text-5xl"), "Visitor activity"),
                div(
                    tw("mt-3 flex flex-wrap items-center justify-between gap-4"),
                    p(
                        tw("max-w-2xl text-stone-400"),
                        "A live ordered stream adds new sessions while cursor "
                        "pagination retrieves older history.",
                    ),
                    self.simulate,
                ),
                div(
                    tw("mt-10 grid gap-5 lg:grid-cols-[14rem_1fr]"),
                    Card(
                        tw("border-stone-700 bg-stone-900 text-stone-50"),
                        CardContent(
                            p(tw("text-sm text-stone-400"), "Recorded visits"),
                            p(
                                tw("mt-2 text-4xl font-semibold"),
                                str(summary.total),
                            ),
                        ),
                    ),
                    Card(
                        tw("border-stone-700 bg-stone-900 text-stone-50"),
                        CardContent(self.chart),
                    ),
                ),
                div(
                    tw("mt-8 overflow-hidden rounded-xl border border-stone-800"),
                    self.events,
                    self.more,
                ),
                div(
                    tw("mt-8"),
                    p(
                        tw("mb-3 text-sm font-medium text-stone-300"),
                        "Raw request log",
                    ),
                    self.log,
                ),
            ),
        )

    def initialize(self):
        session = api.account.visitors.events()
        sequence = self.get_data("stream-sequence")
        session.resume_after(0 if sequence is None else int(sequence))
        session.on_event(self.receive_visit)
        session.on_resync(self.resync)
        session.start()
        self.live = session

    def disconnected(self):
        if self.live is not None:
            self.live.close()

    def reconnected(self):
        if self.live is not None:
            self.live.start()

    def receive_visit(self, visit: VisitorEvent):
        selector = '[data-visitor-event="' + str(visit.id) + '"]'
        if self.events.querySelector(selector) is not None:
            return
        self.events.append_live(*visitor_event_rows([visit]))
        self.log.append_live(*visitor_log_lines([visit]))

    async def resync(self, sequence: int):
        snapshot = await api.account.visitors.snapshot(
            CursorPageRequest(size=4)
        )
        page = snapshot.value
        self.events.replace(*visitor_event_rows(page.items))
        self.log.replace(*visitor_log_lines(page.items))
        self.more.set_cursor(page.next)
        if self.live is not None and self.isConnected:
            self.live.resume_after(snapshot.sequence).start()

    async def simulate_visit(self, event: Event):
        await api.account.visitors.record(
            VisitorDraft(
                path="/products/canvas-field-bag/",
                source="Live demo",
                region="Portland, US",
                device="Desktop",
            )
        )

    async def load_more(self, request: CursorPageRequest):
        page = await api.account.visitors.list(request)
        self.events.add_history(*visitor_event_rows(page.items))
        self.log.add_history(*visitor_log_lines(page.items))
        self.more.set_cursor(page.next)


@js
def inventory_rows(products: list[Product]) -> list[Element]:
    rows: list[Element] = []
    for product in products:
        rows.append(
            tag(
                "label",
                tw(
                    "grid cursor-pointer grid-cols-[auto_1fr_auto] items-center "
                    "gap-4 border-b border-stone-800 px-4 py-4 last:border-0 "
                    "hover:bg-stone-900"
                ),
                {"data-product-id": str(product.id)},
                input(
                    tw("size-4 accent-amber-400"),
                    {"type": "checkbox", "data-inventory-select": ""},
                ),
                div(
                    p(tw("font-medium text-stone-100"), product.name),
                    p(tw("text-sm text-stone-400"), product.description),
                ),
                p(
                    tw("text-sm tabular-nums text-stone-300"),
                    str(product.inventory) + " in stock",
                ),
            )
        )
    return rows


@js
class InventoryPage(Widget):
    def __init__(self, page: Page[Product]):
        super().__init__()
        self.rows = ref(div(*inventory_rows(page.items)))
        self.rows.setAttribute("data-testid", "inventory-rows")
        self.inventory = ref(
            input(
                tw(
                    "h-10 w-28 rounded-md border border-stone-700 bg-stone-950 "
                    "px-3 text-sm text-stone-100"
                ),
                {
                    "type": "number",
                    "min": "0",
                    "value": "0",
                    "data-testid": "bulk-inventory-value",
                },
            )
        )
        self.notice = ref(
            p(
                tw("text-sm text-stone-400"),
                {"aria-live": "polite", "data-testid": "inventory-notice"},
            )
        )
        self.apply_button = ref(Button("Update selected"))
        self.apply_button.setAttribute("data-testid", "bulk-inventory-apply")
        self.apply_button.on_click(self.apply_changes)
        self.pagination = ref(
            CursorPagination(
                page.previous,
                page.next,
                label="Inventory pagination",
                size=10,
            )
        )
        self.pagination.on_page(self.load_page)
        self.add(
            tw("block min-h-screen bg-stone-950 px-5 py-16 text-stone-50 lg:px-8"),
            div(
                tw("mx-auto max-w-5xl"),
                tag(
                    "a",
                    tw("text-sm text-stone-300 hover:text-white"),
                    {"href": "/account/"},
                    "← Account",
                ),
                h1(tw("mt-8 font-serif text-5xl"), "Inventory"),
                p(
                    tw("mt-3 max-w-2xl text-stone-400"),
                    "Select products and apply one validated, atomic stock update.",
                ),
                div(
                    tw(
                        "mt-8 flex flex-wrap items-end gap-3 rounded-xl border "
                        "border-stone-800 bg-stone-900 p-4"
                    ),
                    tag(
                        "label",
                        tw("grid gap-1 text-sm text-stone-300"),
                        "New inventory",
                        self.inventory,
                    ),
                    self.apply_button,
                    self.notice,
                ),
                div(
                    tw("mt-6 overflow-hidden rounded-xl border border-stone-800"),
                    self.rows,
                ),
                div(
                    tw("mt-4 flex justify-end gap-2"),
                    self.pagination,
                ),
            ),
        )

    def selected_changes(self) -> list[InventoryChange]:
        changes: list[InventoryChange] = []
        inventory = int(self.inventory.value)
        for row in self.rows.children:
            control = row.querySelector("[data-inventory-select]")
            product_id = row.getAttribute("data-product-id")
            if isinstance(control, HTMLInputElement) and control.checked:
                if product_id is None:
                    raise ValueError("Inventory row is missing its product ID.")
                changes.append(
                    InventoryChange(product_id=int(product_id), inventory=inventory)
                )
        return changes

    async def apply_changes(self, event: Event):
        changes = self.selected_changes()
        try:
            batch = api.atomic()
            for change in changes:
                batch.add(api.account.inventory.set, change)
            updated = await batch.commit()
        except OperationError as error:
            self.notice.textContent = error.issues[0].detail
            return
        self.notice.textContent = "Updated " + str(len(updated)) + " products."
        await self.load_page(CursorPageRequest(size=10))

    async def load_page(self, request: CursorPageRequest):
        page = await api.account.inventory.list(request)
        self.rows.replaceChildren(*inventory_rows(page.items))
        self.pagination.set_page(page)


@js
def moderation_rows(reviews: list[ModeratedReview]) -> list[Element]:
    rows: list[Element] = []
    for review in reviews:
        publish = Button("Publish", variant="outline", size="sm")
        publish.setAttribute("data-review-action", "published")
        publish.setAttribute("data-review-id", str(review.id))
        reject = Button("Reject", variant="ghost", size="sm")
        reject.setAttribute("data-review-action", "rejected")
        reject.setAttribute("data-review-id", str(review.id))
        if review.status == "published":
            publish.setAttribute("disabled", "")
        elif review.status == "rejected":
            reject.setAttribute("disabled", "")
        rows.append(
            div(
                tw(
                    "grid gap-4 border-b border-stone-800 px-5 py-5 last:border-0 "
                    "lg:grid-cols-[12rem_1fr_auto] lg:items-center"
                ),
                div(
                    p(tw("font-medium text-stone-100"), review.product_name),
                    p(tw("mt-1 text-sm text-stone-400"), review.author_name),
                ),
                div(
                    div(
                        tw("flex items-center gap-2"),
                        Badge(review.status, variant="outline"),
                        span(
                            tw("text-sm text-amber-300"),
                            str(review.rating) + " / 5",
                        ),
                    ),
                    p(tw("mt-2 text-sm leading-6 text-stone-300"), review.body),
                ),
                div(tw("flex items-center gap-2"), publish, reject),
            )
        )
    if not rows:
        rows.append(
            Empty(
                EmptyHeader(
                    EmptyTitle("No reviews to moderate"),
                    EmptyDescription("New customer reviews will appear here."),
                )
            )
        )
    return rows


@js
class ReviewModerationPage(Widget):
    def __init__(self, page: Page[ModeratedReview]):
        super().__init__()
        self.rows = ref(div(*moderation_rows(page.items)))
        self.rows.setAttribute("data-testid", "review-moderation-rows")
        self.pagination = ref(
            CursorPagination(
                page.previous,
                page.next,
                label="Review moderation pagination",
                size=10,
            )
        )
        self.pagination.previous.setAttribute(
            "data-testid", "moderation-previous"
        )
        self.pagination.next.setAttribute("data-testid", "moderation-next")
        self.pagination.on_page(self.load_page)
        self.notice = ref(
            p(
                tw("min-h-5 text-sm text-stone-400"),
                {"aria-live": "polite", "data-testid": "moderation-notice"},
            )
        )
        self.add(
            tw("block min-h-screen bg-stone-950 px-5 py-20 text-stone-50 lg:px-8"),
            div(
                tw("mx-auto max-w-6xl"),
                tag(
                    "a",
                    tw("text-sm text-stone-300 hover:text-white"),
                    {"href": "/account/"},
                    "← Account",
                ),
                h1(tw("mt-8 font-serif text-5xl"), "Review moderation"),
                p(
                    tw("mt-3 max-w-2xl text-stone-400"),
                    "Publish thoughtful customer feedback or reject submissions "
                    "that should not appear in the storefront.",
                ),
                self.notice,
                div(
                    tw("mt-10 overflow-hidden rounded-xl border border-stone-800"),
                    self.rows,
                ),
                div(tw("mt-5 flex justify-end"), self.pagination),
            ),
        )
        self.addEventListener("click", self.clicked)

    async def clicked(self, event: Event):
        target = cast(Element, event.target)
        action = target.closest("[data-review-action]")
        if action is None:
            return
        status = action.getAttribute("data-review-action")
        review_id = action.getAttribute("data-review-id")
        if status is None or review_id is None:
            return
        await self.set_status(int(review_id), cast(ReviewStatus, status))

    async def set_status(self, review_id: int, status: ReviewStatus):
        try:
            review = await api.account.moderation.set_status(review_id, status)
        except OperationError as error:
            self.notice.textContent = error.issues[0].detail
            return
        self.notice.textContent = (
            review.author_name + " is now " + review.status + "."
        )
        await self.load_page(CursorPageRequest(size=10))

    async def load_page(self, request: CursorPageRequest):
        page = await api.account.moderation.list(request)
        self.rows.replaceChildren(*moderation_rows(page.items))
        self.pagination.set_page(page)


@js
class StoreLayout(NavigationLayout):
    def __init__(self, content: Element):
        super().__init__(content, "store")
        self.add(self.outlet)


@js
def application_shell(content: Element) -> Element:
    return StoreLayout(content)


@js
def public_section(content: Element) -> Element:
    return ThemeProvider(
        northstar_theme(),
        div({"data-store-section": "public"}, content),
    )


@js
def account_section(content: Element) -> Element:
    return ThemeProvider(
        northstar_account_theme(),
        div(
            tw("min-h-screen bg-stone-950 text-stone-50"),
            {"data-store-section": "account"},
            content,
        ),
    )


@js
def catalog_page(page: Page[Product]) -> Element:
    return CatalogPage(page)


@js
def account_page(summary: AccountSummary, orders: Page[OrderSummary]) -> Element:
    return AccountDashboard(summary, orders)


@js
def inventory_page(page: Page[Product]) -> Element:
    return InventoryPage(page)


@js
def review_moderation_page(page: Page[ModeratedReview]) -> Element:
    return ReviewModerationPage(page)


@js
def visitor_activity_page(
    summary: TrafficSummary,
    snapshot: StreamSnapshot[Page[VisitorEvent]],
) -> Element:
    return VisitorActivityPage(summary, snapshot)


CATALOG_PAGE = ApplicationPage("catalog", catalog_page)
STORY_PAGE = ApplicationPage("story", story_page)
ACCOUNT_PAGE = ApplicationPage("overview", account_page)
INVENTORY_PAGE = ApplicationPage("inventory", inventory_page)
REVIEW_MODERATION_PAGE = ApplicationPage("reviews", review_moderation_page)
VISITOR_ACTIVITY_PAGE = ApplicationPage("visitors", visitor_activity_page)

STORE_APPLICATION = ApplicationSection(
    "store",
    application_shell,
    (
        ApplicationSection(
            "public",
            public_section,
            (CATALOG_PAGE, STORY_PAGE),
        ),
        ApplicationSection(
            "account",
            account_section,
            (
                ACCOUNT_PAGE,
                INVENTORY_PAGE,
                REVIEW_MODERATION_PAGE,
                VISITOR_ACTIVITY_PAGE,
            ),
        ),
    ),
)
