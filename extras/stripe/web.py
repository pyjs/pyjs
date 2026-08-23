"""Stripe elements that can be included in PyJS server-rendered documents."""

from pyjs.web.domx import tag

from .browser import PRICING_TABLE_JS_URL, STRIPE_JS_URL


def pricing_table(
    pricing_table_id: str,
    publishable_key: str,
    *,
    customer_email: str = "",
    client_reference_id: str = "",
    customer_session_client_secret: str = "",
):
    """Render Stripe's hosted pricing-table Web Component."""
    attributes = {
        "pricing-table-id": pricing_table_id,
        "publishable-key": publishable_key,
    }
    if customer_email:
        attributes["customer-email"] = customer_email
    if client_reference_id:
        attributes["client-reference-id"] = client_reference_id
    if customer_session_client_secret:
        attributes["customer-session-client-secret"] = customer_session_client_secret
    return tag("stripe-pricing-table", attributes)


def stripe_script():
    """Load Stripe.js from Stripe's origin."""
    return tag("script", {"src": STRIPE_JS_URL}, " ")


def pricing_table_script():
    """Load Stripe's hosted pricing-table custom element."""
    return tag(
        "script",
        {"async": "", "src": PRICING_TABLE_JS_URL},
        " ",
    )
