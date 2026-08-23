"""Server-rendered operator interface for the local Stripe simulator."""

from dataclasses import dataclass
from functools import cache

from pyjs import js
from pyjs.transpiler import bundle
from pyjs.web.dom import Element
from pyjs.web.domx import button, div, form, h1, input, p, span, tag, tw
from pyjs.web.ssr import raw_html, render_document


@js
@dataclass(frozen=True)
class SubscriptionView:
    id: str
    customer_email: str
    status: str
    period_end: str
    cancel_at_period_end: bool
    payment_method: str
    renewal_behavior: str
    invoice_id: str = ""
    invoice_status: str = ""
    invoice_attempts: int = 0


@js
@dataclass(frozen=True)
class EventView:
    id: str
    type: str
    created: str
    delivery: str
    attempts: int
    payload: str
    can_resend: bool
    last_response: str
    attempt_history: tuple[str, ...] = ()


@js
@dataclass(frozen=True)
class InvoiceView:
    id: str
    subscription_id: str
    status: str
    billing_reason: str
    attempt_count: int
    next_attempt: str = ""
    error_code: str = ""


@js
@dataclass(frozen=True)
class DashboardView:
    clock: str
    api_base: str
    webhook_url: str
    retry_policy: str
    customer_count: int
    subscription_count: int
    invoice_count: int
    delivery_mode: str
    pending_count: int
    subscriptions: tuple[SubscriptionView, ...]
    invoices: tuple[InvoiceView, ...]
    events: tuple[EventView, ...]


@js
def status_badge(status: str) -> Element:
    if status in ("active", "paid", "delivered"):
        return span(
            tw(
                "inline-flex rounded-full bg-emerald-100 px-2.5 py-1 text-xs "
                "font-semibold text-emerald-800"
            ),
            status.replace("_", " "),
        )
    if status in ("past_due", "open"):
        return span(
            tw(
                "inline-flex rounded-full bg-amber-100 px-2.5 py-1 text-xs "
                "font-semibold text-amber-800"
            ),
            status.replace("_", " "),
        )
    if status in ("canceled", "failed", "unpaid", "uncollectible"):
        return span(
            tw(
                "inline-flex rounded-full bg-red-100 px-2.5 py-1 text-xs "
                "font-semibold text-red-800"
            ),
            status.replace("_", " "),
        )
    return span(
        tw(
            "inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs "
            "font-semibold text-slate-700"
        ),
        status.replace("_", " "),
    )


@js
def metric(label: str, value: str) -> Element:
    return div(
        tw("rounded-xl border border-slate-200 bg-white p-4 shadow-sm"),
        p(tw("text-xs font-medium uppercase tracking-wide text-slate-500"), label),
        p(tw("mt-1 text-2xl font-semibold text-slate-950"), value),
    )


@js
def behavior_option(value: str, label: str, selected: str) -> Element:
    attributes = {"value": value}
    if value == selected:
        attributes["selected"] = ""
    return tag("option", attributes, label)


@js
def subscription_card(subscription: SubscriptionView) -> Element:
    cancellation = "Renews automatically"
    if subscription.cancel_at_period_end:
        cancellation = "Cancellation scheduled"
    invoice: Element = p(
        tw("text-sm text-slate-500"),
        "No open invoice",
    )
    retry: Element = div()
    renew: Element = form(
        {
            "action": "/_simulator/subscriptions/" + subscription.id + "/renew",
            "method": "post",
        },
        button(
            tw(
                "rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold "
                "text-white hover:bg-indigo-500"
            ),
            {"type": "submit"},
            "Run renewal now",
        ),
    )
    if subscription.invoice_id:
        invoice = div(
            tw("flex flex-wrap items-center gap-2 text-sm text-slate-600"),
            span("Latest invoice " + subscription.invoice_id),
            status_badge(subscription.invoice_status),
            span("Attempts " + str(subscription.invoice_attempts)),
        )
        if subscription.invoice_status == "open":
            renew = div()
            retry = form(
                {
                    "action": ("/_simulator/subscriptions/" + subscription.id + "/retry"),
                    "method": "post",
                },
                button(
                    tw(
                        "rounded-lg border border-slate-300 bg-white px-3 py-2 "
                        "text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    ),
                    {"type": "submit"},
                    "Retry open invoice",
                ),
            )
    return tag(
        "article",
        tw("rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"),
        {"data-subscription-id": subscription.id},
        div(
            tw("flex flex-wrap items-start justify-between gap-3"),
            div(
                p(
                    tw("text-sm font-semibold text-slate-950"),
                    subscription.customer_email or "Customer without email",
                ),
                p(tw("mt-1 font-mono text-xs text-slate-500"), subscription.id),
            ),
            status_badge(subscription.status),
        ),
        div(
            tw("mt-4 grid gap-1 text-sm text-slate-600 sm:grid-cols-2"),
            p("Period ends " + subscription.period_end),
            p(subscription.payment_method),
            p(cancellation),
        ),
        div(tw("mt-4"), invoice),
        form(
            tw("mt-5 grid gap-3 sm:grid-cols-[1fr_auto]"),
            {
                "action": ("/_simulator/subscriptions/" + subscription.id + "/behavior"),
                "method": "post",
            },
            tag(
                "label",
                tw("grid gap-1 text-sm font-medium text-slate-700"),
                "Next payment outcome",
                tag(
                    "select",
                    tw(
                        "h-10 rounded-lg border border-slate-300 bg-white px-3 "
                        "text-sm text-slate-950"
                    ),
                    {"name": "behavior"},
                    behavior_option(
                        "success", "Successful payment", subscription.renewal_behavior
                    ),
                    behavior_option(
                        "soft_decline",
                        "Soft decline — retryable",
                        subscription.renewal_behavior,
                    ),
                    behavior_option(
                        "hard_decline",
                        "Hard decline — no retry",
                        subscription.renewal_behavior,
                    ),
                    behavior_option(
                        "authentication_required",
                        "Customer authentication required",
                        subscription.renewal_behavior,
                    ),
                ),
            ),
            button(
                tw(
                    "self-end rounded-lg bg-slate-900 px-4 py-2.5 text-sm "
                    "font-semibold text-white hover:bg-slate-700"
                ),
                {"type": "submit"},
                "Save outcome",
            ),
        ),
        div(
            tw("mt-3 flex flex-wrap gap-3"),
            renew,
            retry,
        ),
        form(
            tw("mt-4 flex flex-wrap items-end gap-3 border-t border-slate-100 pt-4"),
            {
                "action": ("/_simulator/subscriptions/" + subscription.id + "/payment"),
                "method": "post",
            },
            tag(
                "label",
                tw("grid gap-1 text-sm font-medium text-slate-700"),
                "Replace payment method",
                tag(
                    "select",
                    tw(
                        "h-10 rounded-lg border border-slate-300 bg-white px-3 "
                        "text-sm text-slate-950"
                    ),
                    {"name": "card_number"},
                    tag("option", {"value": "4242424242424242"}, "Visa •••• 4242"),
                    tag(
                        "option",
                        {"value": "4000000000000341"},
                        "Retryable Visa •••• 0341",
                    ),
                    tag(
                        "option",
                        {"value": "4000000000000002"},
                        "Declined Visa •••• 0002",
                    ),
                ),
            ),
            button(
                tw(
                    "rounded-lg border border-slate-300 bg-white px-3 py-2 "
                    "text-sm font-semibold text-slate-700 hover:bg-slate-50"
                ),
                {"type": "submit"},
                "Replace and retry",
            ),
        ),
    )


@js
def invoice_row(invoice: InvoiceView) -> Element:
    next_attempt: Element = div()
    if invoice.next_attempt:
        next_attempt = p(
            tw("mt-1 text-xs text-slate-500"),
            "Next payment attempt " + invoice.next_attempt,
        )
    error: Element = div()
    if invoice.error_code:
        error = p(
            tw("mt-1 text-xs font-medium text-red-700"),
            "Last error: " + invoice.error_code,
        )
    return tag(
        "li",
        tw("border-b border-slate-200 py-4 last:border-0"),
        div(
            tw("flex flex-wrap items-start justify-between gap-3"),
            div(
                p(tw("font-mono text-sm font-semibold text-slate-900"), invoice.id),
                p(
                    tw("mt-1 text-xs text-slate-500"),
                    invoice.billing_reason.replace("_", " ")
                    + " · "
                    + invoice.subscription_id,
                ),
            ),
            status_badge(invoice.status),
        ),
        p(
            tw("mt-2 text-xs text-slate-500"),
            "Payment attempts: " + str(invoice.attempt_count),
        ),
        next_attempt,
        error,
    )


@js
def event_row(event: EventView) -> Element:
    resend: Element = div()
    if event.can_resend:
        resend_buttons: list[Element] = []
        for action, label in (
            ("resend", "Send duplicate"),
            ("invalid", "Send bad signature"),
            ("stale", "Send stale signature"),
        ):
            resend_buttons.append(
                form(
                    {
                        "action": "/_simulator/events/" + event.id + "/" + action,
                        "method": "post",
                    },
                    button(
                        tw(
                            "rounded-lg border border-slate-300 bg-white px-3 "
                            "py-2 text-xs font-semibold text-slate-700 "
                            "hover:bg-slate-50"
                        ),
                        {"type": "submit"},
                        label,
                    ),
                )
            )
        resend = div(tw("mt-3 flex flex-wrap gap-2"), *resend_buttons)
    history: list[Element] = []
    for attempt in event.attempt_history:
        history.append(tag("li", tw("mt-1 text-xs text-slate-500"), attempt))
    attempt_details: Element = div()
    if len(history) > 0:
        attempt_details = tag(
            "details",
            tw("mt-3"),
            tag(
                "summary",
                tw("cursor-pointer text-xs font-medium text-slate-700"),
                "Delivery history",
            ),
            tag("ol", *history),
        )
    delivery_detail: Element = div()
    if event.last_response:
        delivery_detail = p(
            tw("mt-1 text-xs text-slate-500"),
            "Last response: " + event.last_response,
        )
    return tag(
        "li",
        tw("border-b border-slate-200 py-4 last:border-0"),
        {"data-event-id": event.id},
        div(
            tw("flex flex-wrap items-start justify-between gap-3"),
            div(
                p(tw("font-mono text-sm font-semibold text-slate-900"), event.type),
                p(
                    tw("mt-1 text-xs text-slate-500"),
                    event.created + " · " + event.id,
                ),
            ),
            status_badge(event.delivery),
        ),
        p(
            tw("mt-2 text-xs text-slate-500"),
            "Webhook delivery attempts: " + str(event.attempts),
        ),
        delivery_detail,
        attempt_details,
        tag(
            "details",
            tw("mt-3 text-sm"),
            tag("summary", tw("cursor-pointer font-medium text-indigo-700"), "Payload"),
            tag(
                "pre",
                tw(
                    "mt-2 max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 "
                    "text-xs text-slate-100"
                ),
                event.payload,
            ),
        ),
        resend,
    )


@js
def dashboard(view: DashboardView) -> Element:
    subscriptions: list[Element] = []
    for subscription in view.subscriptions:
        subscriptions.append(subscription_card(subscription))
    if len(subscriptions) == 0:
        subscriptions.append(
            p(
                tw(
                    "rounded-2xl border border-dashed border-slate-300 bg-white "
                    "p-8 text-center text-sm text-slate-500"
                ),
                "Complete a Checkout session to create a subscription.",
            )
        )
    events: list[Element] = []
    for event in view.events:
        events.append(event_row(event))
    if len(events) == 0:
        events.append(p(tw("py-6 text-sm text-slate-500"), "No events yet."))
    invoices: list[Element] = []
    for invoice in view.invoices:
        invoices.append(invoice_row(invoice))
    if len(invoices) == 0:
        invoices.append(p(tw("py-6 text-sm text-slate-500"), "No invoices yet."))
    webhook = view.webhook_url or "Not configured"
    return tag(
        "main",
        tw("mx-auto w-full max-w-6xl p-4 sm:p-8"),
        tag(
            "header",
            tw("flex flex-wrap items-end justify-between gap-4"),
            div(
                p(
                    tw("text-sm font-semibold uppercase tracking-widest text-indigo-600"),
                    "PyJS Extras",
                ),
                h1(
                    tw("mt-1 text-3xl font-bold tracking-tight text-slate-950"),
                    "Local Stripe simulator",
                ),
                p(
                    tw("mt-2 max-w-2xl text-sm text-slate-600"),
                    "Drive subscription renewals and inspect the webhooks received "
                    "by your application.",
                ),
            ),
            tag(
                "details",
                tw("text-right"),
                tag(
                    "summary",
                    tw("cursor-pointer text-sm font-medium text-red-700"),
                    "Reset simulator…",
                ),
                form(
                    tw("mt-2"),
                    {"action": "/_simulator/reset", "method": "post"},
                    button(
                        tw(
                            "rounded-lg border border-red-200 bg-white px-4 "
                            "py-2.5 text-sm font-semibold text-red-700 "
                            "hover:bg-red-50"
                        ),
                        {"type": "submit"},
                        "Delete all simulator data",
                    ),
                ),
            ),
        ),
        div(
            tw("mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"),
            metric("Customers", str(view.customer_count)),
            metric("Subscriptions", str(view.subscription_count)),
            metric("Invoices", str(view.invoice_count)),
            metric("Simulator time", view.clock),
        ),
        div(
            tw("mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"),
            p(tw("text-sm text-slate-600"), "API base: " + view.api_base),
            p(tw("mt-1 text-sm text-slate-600"), "Webhook: " + webhook),
            p(
                tw("mt-1 text-sm text-slate-600"),
                "Retry policy: " + view.retry_policy,
            ),
            form(
                tw("mt-4 flex flex-wrap items-end gap-3"),
                {"action": "/_simulator/delivery/mode", "method": "post"},
                tag(
                    "label",
                    tw("grid gap-1 text-sm font-medium text-slate-700"),
                    "Webhook delivery",
                    tag(
                        "select",
                        tw(
                            "h-10 rounded-lg border border-slate-300 bg-white "
                            "px-3 text-sm text-slate-950"
                        ),
                        {"name": "mode"},
                        behavior_option("automatic", "Automatic", view.delivery_mode),
                        behavior_option("manual", "Manual", view.delivery_mode),
                        behavior_option("paused", "Paused", view.delivery_mode),
                    ),
                ),
                button(
                    tw(
                        "rounded-lg border border-slate-300 bg-white px-4 py-2.5 "
                        "text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    ),
                    {"type": "submit"},
                    "Set mode",
                ),
                span(
                    tw("self-center text-xs text-slate-500"),
                    str(view.pending_count) + " pending or failed",
                ),
            ),
            div(
                tw("mt-3 flex flex-wrap gap-2"),
                form(
                    {
                        "action": "/_simulator/delivery/pending/oldest",
                        "method": "post",
                    },
                    button(
                        tw(
                            "rounded-lg border border-slate-300 px-3 py-2 text-xs "
                            "font-semibold text-slate-700 hover:bg-slate-50"
                        ),
                        {"type": "submit"},
                        "Deliver oldest first",
                    ),
                ),
                form(
                    {
                        "action": "/_simulator/delivery/pending/newest",
                        "method": "post",
                    },
                    button(
                        tw(
                            "rounded-lg border border-slate-300 px-3 py-2 text-xs "
                            "font-semibold text-slate-700 hover:bg-slate-50"
                        ),
                        {"type": "submit"},
                        "Deliver newest first",
                    ),
                ),
            ),
            form(
                tw("mt-4 flex flex-wrap items-end gap-3"),
                {"action": "/_simulator/clock/advance", "method": "post"},
                tag(
                    "label",
                    tw("grid gap-1 text-sm font-medium text-slate-700"),
                    "Advance time by days",
                    input(
                        tw("h-10 w-28 rounded-lg border border-slate-300 px-3"),
                        {
                            "max": "366",
                            "min": "1",
                            "name": "days",
                            "type": "number",
                            "value": "30",
                        },
                    ),
                ),
                button(
                    tw(
                        "rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold "
                        "text-white hover:bg-indigo-500"
                    ),
                    {"type": "submit"},
                    "Advance clock",
                ),
            ),
        ),
        tag(
            "section",
            tw("mt-10"),
            tag("h2", tw("text-xl font-semibold text-slate-950"), "Subscriptions"),
            div(tw("mt-4 grid gap-4"), *subscriptions),
        ),
        tag(
            "section",
            tw("mt-10 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"),
            tag("h2", tw("text-xl font-semibold text-slate-950"), "Invoices"),
            tag("ol", tw("mt-2"), *invoices),
        ),
        tag(
            "section",
            tw("mt-10 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"),
            tag("h2", tw("text-xl font-semibold text-slate-950"), "Event deliveries"),
            tag("ol", tw("mt-2"), *events),
        ),
    )


def main():
    return dashboard(
        DashboardView(
            clock="Now",
            api_base="http://127.0.0.1:12111/v1",
            webhook_url="",
            retry_policy="3 payment attempts",
            customer_count=0,
            subscription_count=0,
            invoice_count=0,
            delivery_mode="automatic",
            pending_count=0,
            subscriptions=(),
            invoices=(),
            events=(),
        )
    )


@cache
def stylesheet() -> str:
    _, stylesheet = bundle(main, include_main=False)
    return stylesheet


def document(view: DashboardView) -> str:
    return render_document(
        tag(
            "html",
            {"lang": "en"},
            tag(
                "head",
                tag("meta", {"charset": "utf-8"}),
                tag(
                    "meta",
                    {
                        "content": "width=device-width, initial-scale=1",
                        "name": "viewport",
                    },
                ),
                tag("title", "Local Stripe simulator"),
                tag("style", raw_html(stylesheet())),
            ),
            tag("body", tw("min-h-screen bg-slate-50 text-slate-950"), dashboard(view)),
        )
    )
