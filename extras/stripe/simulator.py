"""Stateful local simulator for Stripe subscription billing workflows."""

import argparse
import json
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any, Self
from urllib.parse import parse_qs

from pyjs.server.dev import Application, Server

from .simulator_delivery import WebhookDelivery
from .simulator_store import SimulatorStore
from .simulator_types import (
    AUTHENTICATION_CARD,
    DECLINED_CARD,
    RENEWAL_BEHAVIORS,
    RENEWAL_FAILURE_CARD,
    SUCCESS_CARD,
    SimulatorHTTPError,
    SimulatorOptions,
    status_text,
)
from .simulator_ui import (
    DashboardView,
    EventView,
    InvoiceView,
    SubscriptionView,
)
from .simulator_ui import (
    document as simulator_document,
)


class StripeSimulator:
    """WSGI application implementing the Stripe subset used by PyJS Extras."""

    def __init__(self, store: SimulatorStore, options: SimulatorOptions):
        self.store = store
        self.options = options
        self._state_lock = threading.RLock()
        self.delivery = WebhookDelivery(
            store,
            options.webhook_url,
            options.webhook_secret,
        )
        self._seed_catalog()

    def _seed_catalog(self) -> None:
        product = {
            "id": self.options.product_id,
            "object": "product",
            "active": True,
            "name": self.options.product_name,
            "description": "Local subscription used by the Stripe simulator.",
        }
        price = {
            "id": self.options.price_id,
            "object": "price",
            "active": True,
            "currency": self.options.currency,
            "unit_amount": self.options.unit_amount,
            "product": product["id"],
            "recurring": {"interval": "month", "interval_count": 1},
            "type": "recurring",
        }
        if self.store.get("product", product["id"]) is None:
            self.store.put("product", product)
        if self.store.get("price", price["id"]) is None:
            self.store.put("price", price)

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/").rstrip("/") or "/"
        try:
            if self._delivers_webhook(method, path):
                result = self._request(method, path, environ)
            else:
                with self._state_lock:
                    result = self._request(method, path, environ)
        except SimulatorHTTPError as error:
            result = self._json(
                {
                    "error": {
                        "type": error.error_type,
                        "message": error.message,
                    }
                },
                error.status,
            )
        status, headers, body = result
        start_response(status, headers)
        return [body]

    def _request(self, method: str, path: str, environ):
        if path.startswith("/v1/"):
            self._authenticate(environ)
            if api_version := environ.get("HTTP_STRIPE_VERSION"):
                self.store.set_metadata("api_version", api_version)
        return self._dispatch(method, path, environ)

    @staticmethod
    def _delivers_webhook(method: str, path: str) -> bool:
        if method != "POST":
            return False
        return path.startswith("/_simulator/events/") or path.startswith(
            "/_simulator/delivery/pending/"
        )

    def _authenticate(self, environ) -> None:
        authorization = environ.get("HTTP_AUTHORIZATION", "")
        if authorization != f"Bearer {self.options.api_key}":
            raise SimulatorHTTPError(401, "invalid_api_key", "Invalid API Key")

    def _dispatch(self, method: str, path: str, environ):
        if method == "GET" and path == "/":
            return self._html(self._home())
        if method == "GET" and path == "/v1/products":
            return self._json(self._list("product"))
        if method == "GET" and path.startswith("/v1/products/"):
            return self._object("product", path.rsplit("/", 1)[-1])
        if method == "GET" and path == "/v1/prices":
            return self._json(self._list("price"))
        if method == "GET" and path.startswith("/v1/prices/"):
            return self._object("price", path.rsplit("/", 1)[-1])
        if method == "POST" and path == "/v1/checkout/sessions":
            return self._create_checkout(path, environ)
        if method == "POST" and path.startswith("/v1/checkout/sessions/") and path.endswith("/expire"):
            return self._expire_checkout(path, environ)
        if method == "GET" and path.startswith("/v1/checkout/sessions/"):
            return self._json(self._checkout_session(path.rsplit("/", 1)[-1]))
        if method == "GET" and path == "/v1/invoices":
            return self._list_invoices(environ)
        if method == "GET" and path.startswith("/v1/invoices/"):
            return self._object("invoice", path.rsplit("/", 1)[-1])
        if method == "POST" and path == "/v1/billing_portal/sessions":
            return self._create_portal(path, environ)
        if method == "GET" and path == "/v1/customers":
            return self._json(self._list("customer"))
        if method == "GET" and path.startswith("/v1/customers/"):
            return self._object("customer", path.rsplit("/", 1)[-1])
        if method == "GET" and path == "/v1/subscriptions":
            params = self._query(environ)
            values = self.store.list("subscription")
            if params.get("customer"):
                values = [
                    item for item in values if item["customer"] == params["customer"]
                ]
            return self._json(self._list_values(values))
        if path.startswith("/v1/subscriptions/"):
            subscription_id = path.rsplit("/", 1)[-1]
            if method == "GET":
                return self._object("subscription", subscription_id)
            if method == "POST":
                return self._update_subscription(subscription_id, environ)
        if method == "GET" and path.startswith("/checkout/"):
            return self._checkout_page(path.rsplit("/", 1)[-1])
        if (
            method == "POST"
            and path.startswith("/checkout/")
            and path.endswith("/complete")
        ):
            session_id = path.removeprefix("/checkout/").removesuffix("/complete")
            return self._complete_checkout(session_id, environ)
        if (
            method == "POST"
            and path.startswith("/checkout/")
            and path.endswith("/authenticate")
        ):
            session_id = path.removeprefix("/checkout/").removesuffix("/authenticate")
            return self._complete_checkout(session_id, environ, authenticated=True)
        if method == "GET" and path.startswith("/portal/"):
            return self._portal_page(path.rsplit("/", 1)[-1])
        if method == "POST" and path.startswith("/portal/"):
            parts = path.split("/")
            if len(parts) != 4:
                raise SimulatorHTTPError(404, "invalid_request_error", "No such endpoint")
            _, _, session_id, action = parts
            return self._portal_action(session_id, action)
        if method == "GET" and path == "/_test/state":
            return self._json(self._state())
        if method == "POST" and path == "/_test/reset":
            self.reset()
            return self._json({"reset": True})
        if method == "POST" and path == "/_test/clock/advance":
            return self._advance_clock(environ)
        if method == "POST" and path == "/_simulator/reset":
            self.reset()
            return self._redirect("/")
        if method == "POST" and path == "/_simulator/clock/advance":
            self._advance_clock(environ)
            return self._redirect("/")
        if method == "POST" and path == "/_simulator/delivery/mode":
            return self._delivery_mode(environ)
        if method == "POST" and path.startswith("/_simulator/delivery/pending/"):
            return self._deliver_pending(path.rsplit("/", 1)[-1])
        if method == "POST" and path.startswith("/_simulator/subscriptions/"):
            return self._subscription_action(path, environ)
        if method == "POST" and path.startswith("/_simulator/events/"):
            return self._event_action(path)
        raise SimulatorHTTPError(404, "invalid_request_error", "No such endpoint")

    def _create_checkout(self, path: str, environ):
        key = environ.get("HTTP_IDEMPOTENCY_KEY", "")
        if existing := self.store.idempotent(path, key):
            return self._json(existing)
        form = self._form(environ)
        price_id = form.get("line_items[0][price]", "")
        now = self.store.now()
        try:
            expires_at = int(form.get("expires_at", str(now + 86400)))
        except ValueError:
            raise SimulatorHTTPError(400, "invalid_request_error", "Invalid checkout expiry") from None
        if not now + 1800 <= expires_at <= now + 86400:
            raise SimulatorHTTPError(400, "invalid_request_error", "Checkout expiry must be 30 minutes to 24 hours away")
        if self.store.get("price", price_id) is None:
            raise SimulatorHTTPError(
                400,
                "invalid_request_error",
                f"No such price: '{price_id}'",
            )
        session_id = self.store.new_id("cs")
        metadata = self._nested(form, "metadata")
        subscription_metadata = self._nested(form, "subscription_data[metadata]")
        value = {
            "id": session_id,
            "object": "checkout.session",
            "created": now,
            "expires_at": expires_at,
            "mode": form.get("mode", "subscription"),
            "client_reference_id": form.get("client_reference_id"),
            "customer": form.get("customer") or None,
            "customer_email": form.get("customer_email"),
            "subscription": None,
            "metadata": metadata,
            "payment_status": "unpaid",
            "status": "open",
            "success_url": form.get("success_url", ""),
            "cancel_url": form.get("cancel_url", ""),
            "price_id": price_id,
            "subscription_metadata": subscription_metadata,
            "url": f"{self.options.public_url}/checkout/{session_id}",
        }
        self.store.put("checkout.session", value)
        self.store.remember(path, key, value)
        return self._json(value)

    def _checkout_session(self, session_id: str) -> dict[str, Any]:
        session = self._required("checkout.session", session_id)
        if session["status"] == "open" and session.get("expires_at", float("inf")) <= self.store.now():
            session = self._expire_session(session)
        return session

    def _expire_session(self, session: dict[str, Any]) -> dict[str, Any]:
        session.update(status="expired", url=None)
        session.pop("card_number", None)
        self.store.put("checkout.session", session)
        self._emit("checkout.session.expired", session)
        return session

    def _expire_checkout(self, path: str, environ):
        key = environ.get("HTTP_IDEMPOTENCY_KEY", "")
        if existing := self.store.idempotent(path, key):
            return self._json(existing)
        session = self._checkout_session(path.split("/")[-2])
        if session["status"] != "open":
            raise SimulatorHTTPError(400, "invalid_request_error", "Only an open checkout can expire")
        session = self._expire_session(session)
        self.store.remember(path, key, session)
        return self._json(session)

    def _list_invoices(self, environ):
        params = self._query(environ)
        if "ending_before" in params:
            raise SimulatorHTTPError(400, "invalid_request_error", "Only starting_after pagination is supported")
        supported = {"customer", "subscription", "status", "limit", "starting_after"}
        if unsupported := sorted(params.keys() - supported):
            raise SimulatorHTTPError(
                400, "invalid_request_error",
                f"Unsupported invoice list parameter: {unsupported[0]}",
            )
        try:
            limit = int(params.get("limit", "10"))
        except ValueError:
            raise SimulatorHTTPError(400, "invalid_request_error", "Invalid invoice limit") from None
        if not 1 <= limit <= 100:
            raise SimulatorHTTPError(400, "invalid_request_error", "Invoice limit must be 1 to 100")
        invoices = sorted(reversed(self.store.list("invoice")), key=lambda value: value["created"], reverse=True)
        for field in ("customer", "subscription", "status"):
            if field in params:
                invoices = [invoice for invoice in invoices if invoice.get(field) == params[field]]
        if cursor := params.get("starting_after"):
            positions = [index for index, invoice in enumerate(invoices) if invoice["id"] == cursor]
            if not positions:
                raise SimulatorHTTPError(400, "invalid_request_error", "Unknown invoice cursor")
            invoices = invoices[positions[0] + 1:]
        return self._json({"object": "list", "data": invoices[:limit],
                           "has_more": len(invoices) > limit, "url": "/v1/invoices"})

    def _create_portal(self, path: str, environ):
        key = environ.get("HTTP_IDEMPOTENCY_KEY", "")
        if existing := self.store.idempotent(path, key):
            return self._json(existing)
        form = self._form(environ)
        customer_id = form.get("customer", "")
        if self.store.get("customer", customer_id) is None:
            raise SimulatorHTTPError(
                400,
                "invalid_request_error",
                f"No such customer: '{customer_id}'",
            )
        session_id = self.store.new_id("bps")
        value = {
            "id": session_id,
            "object": "billing_portal.session",
            "customer": customer_id,
            "return_url": form.get("return_url", ""),
            "url": f"{self.options.public_url}/portal/{session_id}",
        }
        self.store.put("billing_portal.session", value)
        self.store.remember(path, key, value)
        return self._json(value)

    def _complete_checkout(
        self,
        session_id: str,
        environ,
        *,
        authenticated: bool = False,
    ):
        session = self._checkout_session(session_id)
        form = self._form(environ)
        card_number = form.get("card_number", session.get("card_number", ""))
        card_number = card_number.replace(" ", "")
        if session["status"] == "complete":
            return self._redirect(self._success_url(session))
        if session["status"] != "open":
            raise SimulatorHTTPError(400, "invalid_request_error", "Checkout has expired")
        if card_number == DECLINED_CARD:
            return self._checkout_page(session_id, "Your card was declined.", 402)
        if card_number == AUTHENTICATION_CARD and not authenticated:
            session["card_number"] = card_number
            self.store.put("checkout.session", session)
            return self._authentication_page(session)
        if card_number not in {
            SUCCESS_CARD,
            AUTHENTICATION_CARD,
            RENEWAL_FAILURE_CARD,
        }:
            return self._checkout_page(
                session_id,
                "Use a supported Stripe test card number.",
                402,
            )
        customer = self._customer_for_checkout(session)
        subscription = self._subscription_for_checkout(session, customer, card_number)
        session.update(
            {
                "customer": customer["id"],
                "subscription": subscription["id"],
                "payment_status": "paid",
                "status": "complete",
            }
        )
        session.pop("card_number", None)
        self.store.put("checkout.session", session)
        invoice = self._new_invoice(subscription, "subscription_create")
        self._emit("invoice.created", invoice)
        invoice = self._finalize_invoice(invoice)
        self._emit("invoice.finalized", invoice)
        invoice.update(
            {
                "status": "paid",
                "paid": True,
                "attempted": True,
                "amount_paid": invoice["amount_due"],
                "attempt_count": 1,
                "paid_at": self.store.now(),
            }
        )
        self.store.put("invoice", invoice)
        for event_type, source in (
            ("checkout.session.completed", session),
            ("customer.subscription.created", subscription),
            ("invoice.paid", invoice),
        ):
            self._emit(event_type, source)
        return self._redirect(self._success_url(session))

    def _customer_for_checkout(self, session: Mapping[str, Any]) -> dict[str, Any]:
        customer_id = session.get("customer")
        if customer_id:
            return self._required("customer", customer_id)
        customer_id = self.store.new_id("cus")
        return self.store.put(
            "customer",
            {
                "id": customer_id,
                "object": "customer",
                "email": session.get("customer_email", ""),
                "metadata": dict(session.get("metadata", {})),
            },
        )

    def _subscription_for_checkout(
        self,
        session: Mapping[str, Any],
        customer: Mapping[str, Any],
        card_number: str,
    ) -> dict[str, Any]:
        price = self._required("price", session["price_id"])
        now = self.store.now()
        subscription_id = self.store.new_id("sub")
        subscription = self.store.put(
            "subscription",
            {
                "id": subscription_id,
                "object": "subscription",
                "customer": customer["id"],
                "status": "active",
                "cancel_at_period_end": False,
                "current_period_start": now,
                "current_period_end": now + 30 * 24 * 60 * 60,
                "livemode": False,
                "metadata": dict(session.get("subscription_metadata", {})),
                "default_payment_method": {
                    "id": self.store.new_id("pm"),
                    "object": "payment_method",
                    "type": "card",
                    "card": {
                        "brand": "visa",
                        "last4": card_number[-4:],
                    },
                },
                "items": {
                    "object": "list",
                    "data": [
                        {
                            "id": self.store.new_id("si"),
                            "object": "subscription_item",
                            "price": price,
                            "quantity": 1,
                        }
                    ],
                },
            },
        )
        if card_number == RENEWAL_FAILURE_CARD:
            self.set_renewal_behavior(subscription_id, "soft_decline")
        return subscription

    def _new_invoice(
        self,
        subscription: Mapping[str, Any],
        billing_reason: str,
    ) -> dict[str, Any]:
        now = self.store.now()
        return self.store.put(
            "invoice",
            {
                "id": self.store.new_id("in"),
                "object": "invoice",
                "customer": subscription["customer"],
                "subscription": subscription["id"],
                "status": "draft",
                "paid": False,
                "amount_due": subscription["items"]["data"][0]["price"]["unit_amount"],
                "amount_paid": 0,
                "currency": subscription["items"]["data"][0]["price"]["currency"],
                "attempt_count": 0,
                "attempted": False,
                "auto_advance": True,
                "billing_reason": billing_reason,
                "collection_method": "charge_automatically",
                "created": now,
                "finalized_at": None,
                "paid_at": None,
                "period_start": subscription["current_period_start"],
                "period_end": subscription["current_period_end"],
                "next_payment_attempt": None,
                "last_payment_error": None,
            },
        )

    def _finalize_invoice(self, invoice: dict[str, Any]) -> dict[str, Any]:
        invoice.update(
            {
                "status": "open",
                "finalized_at": self.store.now(),
            }
        )
        return self.store.put("invoice", invoice)

    def renewal_behavior(self, subscription_id: str) -> str:
        return self.store.metadata(f"renewal_behavior:{subscription_id}") or "success"

    def set_renewal_behavior(self, subscription_id: str, behavior: str) -> None:
        self._required("subscription", subscription_id)
        if behavior not in RENEWAL_BEHAVIORS:
            raise SimulatorHTTPError(
                400,
                "invalid_request_error",
                f"Unsupported renewal behavior: '{behavior}'",
            )
        self.store.set_metadata(f"renewal_behavior:{subscription_id}", behavior)

    def renew_subscription(self, subscription_id: str) -> dict[str, Any]:
        subscription = self._required("subscription", subscription_id)
        if subscription["status"] in {"canceled", "unpaid"}:
            raise SimulatorHTTPError(
                400,
                "invalid_request_error",
                "A terminal subscription cannot renew",
            )
        if subscription["cancel_at_period_end"]:
            subscription["status"] = "canceled"
            self.store.put("subscription", subscription)
            self._emit("customer.subscription.deleted", subscription)
            return subscription
        if self._open_invoice(subscription_id) is not None:
            raise SimulatorHTTPError(
                400,
                "invalid_request_error",
                "Retry the subscription's open invoice before renewing",
            )
        return self._attempt_subscription_payment(subscription, renewal=True)

    def retry_subscription(self, subscription_id: str) -> dict[str, Any]:
        subscription = self._required("subscription", subscription_id)
        invoice = self._open_invoice(subscription_id)
        if invoice is None:
            raise SimulatorHTTPError(
                400,
                "invalid_request_error",
                "The subscription has no open invoice to retry",
            )
        return self._attempt_subscription_payment(
            subscription,
            renewal=False,
            invoice=invoice,
        )

    def _open_invoice(self, subscription_id: str) -> dict[str, Any] | None:
        invoices = [
            invoice
            for invoice in self.store.list("invoice")
            if invoice["subscription"] == subscription_id and invoice["status"] == "open"
        ]
        return invoices[-1] if invoices else None

    def _attempt_subscription_payment(
        self,
        subscription: dict[str, Any],
        *,
        renewal: bool,
        invoice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        behavior = self.renewal_behavior(subscription["id"])
        if renewal:
            period_start = max(self.store.now(), subscription["current_period_end"])
            subscription["current_period_start"] = period_start
            subscription["current_period_end"] = period_start + 30 * 24 * 60 * 60
        if invoice is not None:
            invoice["attempt_count"] = int(invoice.get("attempt_count", 0)) + 1
        if invoice is None:
            invoice = self._new_invoice(subscription, "subscription_cycle")
            self._emit("invoice.created", invoice)
            invoice = self._finalize_invoice(invoice)
            self._emit("invoice.finalized", invoice)
            invoice["attempt_count"] = 1
        invoice["attempted"] = True
        if behavior == "success":
            invoice.update(
                {
                    "status": "paid",
                    "paid": True,
                    "amount_paid": invoice["amount_due"],
                    "next_payment_attempt": None,
                    "last_payment_error": None,
                    "paid_at": self.store.now(),
                }
            )
            self.store.put("invoice", invoice)

        if behavior == "success":
            subscription["status"] = "active"
            self.store.put("subscription", subscription)
            self._emit("invoice.paid", invoice)
            self._emit("customer.subscription.updated", subscription)
            return subscription

        error = {
            "type": "card_error",
            "code": "authentication_required"
            if behavior == "authentication_required"
            else "card_declined",
            "decline_code": "do_not_honor"
            if behavior == "hard_decline"
            else "insufficient_funds",
        }
        attempts = int(invoice["attempt_count"])
        exhausted = (
            behavior == "soft_decline" and attempts >= self.options.max_payment_attempts
        )
        retry_days = 1 if attempts == 1 else 3
        invoice.update(
            {
                "status": "uncollectible" if exhausted else "open",
                "paid": False,
                "amount_paid": 0,
                "last_payment_error": error,
                "next_payment_attempt": (
                    self.store.now() + retry_days * 24 * 60 * 60
                    if behavior == "soft_decline" and not exhausted
                    else None
                ),
            }
        )
        self.store.put("invoice", invoice)
        subscription["status"] = "unpaid" if exhausted else "past_due"
        self.store.put("subscription", subscription)
        event_type = (
            "invoice.payment_action_required"
            if behavior == "authentication_required"
            else "invoice.payment_failed"
        )
        self._emit(event_type, invoice)
        if exhausted:
            self._emit("invoice.marked_uncollectible", invoice)
        self._emit("customer.subscription.updated", subscription)
        return subscription

    def replace_payment_method(
        self,
        subscription_id: str,
        card_number: str = SUCCESS_CARD,
        *,
        retry: bool = True,
    ) -> dict[str, Any]:
        subscription = self._required("subscription", subscription_id)
        behavior = {
            DECLINED_CARD: "hard_decline",
            AUTHENTICATION_CARD: "authentication_required",
            RENEWAL_FAILURE_CARD: "soft_decline",
        }.get(card_number, "success")
        payment_method = {
            "id": self.store.new_id("pm"),
            "object": "payment_method",
            "type": "card",
            "card": {"brand": "visa", "last4": card_number[-4:]},
        }
        subscription["default_payment_method"] = payment_method
        self.store.put("subscription", subscription)
        self.set_renewal_behavior(subscription_id, behavior)
        self._emit("payment_method.attached", payment_method)
        self._emit("customer.subscription.updated", subscription)
        if retry and self._open_invoice(subscription_id) is not None:
            return self.retry_subscription(subscription_id)
        return subscription

    def _update_subscription(self, subscription_id: str, environ):
        subscription = self._required("subscription", subscription_id)
        form = self._form(environ)
        if "cancel_at_period_end" in form:
            subscription["cancel_at_period_end"] = self._boolean(
                form["cancel_at_period_end"]
            )
        self.store.put("subscription", subscription)
        self._emit("customer.subscription.updated", subscription)
        return self._json(subscription)

    def _checkout_page(
        self,
        session_id: str,
        error: str = "",
        status: int = 200,
    ):
        session = self._checkout_session(session_id)
        price = self._required("price", session["price_id"])
        if session["status"] == "complete":
            return self._redirect(self._success_url(session))
        if session["status"] != "open":
            return self._html(self._document("Checkout expired", "<main><h1>Checkout expired</h1></main>"), 410)
        error_html = f'<p class="error">{escape(error)}</p>' if error else ""
        body = f"""
        <main>
          <p class="eyebrow">Local Stripe simulator</p>
          <h1>Subscribe</h1>
          <p class="price">${price["unit_amount"] / 100:.2f} per month</p>
          <p>{escape(session.get("customer_email", ""))}</p>
          {error_html}
          <form method="post" action="/checkout/{escape(session_id)}/complete">
            <label>Card number
              <input name="card_number" inputmode="numeric"
                     autocomplete="cc-number" value="{SUCCESS_CARD}" required>
            </label>
            <label>Expiration <input value="12/34" autocomplete="cc-exp"></label>
            <label>CVC <input value="123" autocomplete="cc-csc"></label>
            <button type="submit">Subscribe</button>
          </form>
          <p class="hint">Success: 4242 4242 4242 4242</p>
          <p class="hint">Decline: 4000 0000 0000 0002</p>
          <p class="hint">Authentication: 4000 0025 0000 3155</p>
          <a href="{escape(session["cancel_url"])}">Cancel</a>
        </main>
        """
        return self._html(self._document("Stripe Checkout", body), status)

    def _authentication_page(self, session: Mapping[str, Any]):
        body = f"""
        <main>
          <p class="eyebrow">Local Stripe simulator</p>
          <h1>Confirm this payment</h1>
          <p>This test card requires additional authentication.</p>
          <form method="post"
                action="/checkout/{escape(session["id"])}/authenticate">
            <button type="submit">Complete authentication</button>
          </form>
          <a href="{escape(session["cancel_url"])}">Fail authentication</a>
        </main>
        """
        return self._html(self._document("Payment authentication", body))

    def _portal_page(self, session_id: str):
        session = self._required("billing_portal.session", session_id)
        subscriptions = [
            item
            for item in self.store.list("subscription")
            if item["customer"] == session["customer"] and item["status"] != "canceled"
        ]
        if not subscriptions:
            raise SimulatorHTTPError(
                400, "invalid_request_error", "Customer has no subscription"
            )
        subscription = subscriptions[-1]
        action = "resume" if subscription["cancel_at_period_end"] else "cancel"
        label = "Resume subscription" if action == "resume" else "Cancel at period end"
        body = f"""
        <main>
          <p class="eyebrow">Local Stripe simulator</p>
          <h1>Manage subscription</h1>
          <p>Status: {escape(subscription["status"])}</p>
          <p>Visa ending in
             {escape(subscription["default_payment_method"]["card"]["last4"])}</p>
          <form method="post"
                action="/portal/{escape(session_id)}/{action}">
            <button type="submit">{label}</button>
          </form>
          <a href="{escape(session["return_url"])}">Return to application</a>
        </main>
        """
        return self._html(self._document("Stripe Customer Portal", body))

    def _portal_action(self, session_id: str, action: str):
        session = self._required("billing_portal.session", session_id)
        if action not in {"cancel", "resume"}:
            raise SimulatorHTTPError(404, "invalid_request_error", "Unknown action")
        subscriptions = [
            item
            for item in self.store.list("subscription")
            if item["customer"] == session["customer"] and item["status"] != "canceled"
        ]
        if not subscriptions:
            raise SimulatorHTTPError(
                400, "invalid_request_error", "Customer has no subscription"
            )
        subscription = subscriptions[-1]
        subscription["cancel_at_period_end"] = action == "cancel"
        self.store.put("subscription", subscription)
        self._emit("customer.subscription.updated", subscription)
        status = "canceled" if action == "cancel" else "resumed"
        separator = "&" if "?" in session["return_url"] else "?"
        return self._redirect(f"{session['return_url']}{separator}status={status}")

    def _advance_clock(self, environ):
        form = self._form(environ)
        try:
            days = int(form.get("days", "30"))
        except ValueError:
            raise SimulatorHTTPError(
                400, "invalid_request_error", "days must be an integer"
            ) from None
        return self._json(self.advance_clock(days))

    def advance_clock(self, days: int) -> dict[str, Any]:
        if days < 1 or days > 366:
            raise SimulatorHTTPError(
                400, "invalid_request_error", "days must be between 1 and 366"
            )
        now = self.store.advance(days * 24 * 60 * 60)
        for session in self.store.list("checkout.session"):
            self._checkout_session(session["id"])
        changed: list[str] = []
        for subscription in self.store.list("subscription"):
            if subscription["status"] in {"canceled", "unpaid"}:
                continue
            if subscription["status"] == "past_due":
                if (
                    subscription["cancel_at_period_end"]
                    and subscription["current_period_end"] <= now
                ):
                    self.renew_subscription(subscription["id"])
                    changed.append(subscription["id"])
                    continue
                invoice = self._open_invoice(subscription["id"])
                if (
                    invoice is not None
                    and invoice.get("next_payment_attempt") is not None
                    and invoice["next_payment_attempt"] <= now
                ):
                    self.retry_subscription(subscription["id"])
                    changed.append(subscription["id"])
                continue
            if subscription["current_period_end"] > now:
                continue
            if subscription["cancel_at_period_end"]:
                self.renew_subscription(subscription["id"])
                changed.append(subscription["id"])
                continue
            self.renew_subscription(subscription["id"])
            changed.append(subscription["id"])
        return {"now": now, "subscriptions": changed}

    def _subscription_action(self, path: str, environ):
        parts = path.removeprefix("/_simulator/subscriptions/").split("/")
        if len(parts) != 2:
            raise SimulatorHTTPError(404, "invalid_request_error", "Unknown action")
        subscription_id, action = parts
        if action == "behavior":
            self.set_renewal_behavior(
                subscription_id,
                self._form(environ).get("behavior", ""),
            )
        elif action == "renew":
            self.renew_subscription(subscription_id)
        elif action == "retry":
            self.retry_subscription(subscription_id)
        elif action == "payment":
            form = self._form(environ)
            self.replace_payment_method(
                subscription_id,
                form.get("card_number", SUCCESS_CARD).replace(" ", ""),
                retry=self._boolean(form.get("retry", "true")),
            )
        else:
            raise SimulatorHTTPError(404, "invalid_request_error", "Unknown action")
        return self._redirect("/")

    def _event_action(self, path: str):
        parts = path.removeprefix("/_simulator/events/").split("/")
        if len(parts) != 2 or parts[1] not in {"resend", "invalid", "stale"}:
            raise SimulatorHTTPError(404, "invalid_request_error", "Unknown action")
        event = self.store.event(parts[0])
        if event is None:
            raise SimulatorHTTPError(404, "invalid_request_error", "No such event")
        signature_mode = {
            "resend": "valid",
            "invalid": "invalid",
            "stale": "stale",
        }[parts[1]]
        self.delivery.deliver(event, signature_mode=signature_mode)
        return self._redirect("/")

    def _delivery_mode(self, environ):
        mode = self._form(environ).get("mode", "")
        try:
            self.delivery.set_mode(mode)
        except ValueError as error:
            raise SimulatorHTTPError(400, "invalid_request_error", str(error)) from error
        return self._redirect("/")

    def _deliver_pending(self, order: str):
        if order not in {"oldest", "newest"}:
            raise SimulatorHTTPError(404, "invalid_request_error", "Unknown action")
        events = [
            event
            for event in self.store.events()
            if event["delivery_state"] in {"pending", "failed"}
        ]
        if order == "newest":
            events.reverse()
        for event in events:
            self.delivery.deliver(event)
        return self._redirect("/")

    def _emit(self, event_type: str, source: Mapping[str, Any]) -> None:
        event = {
            "id": self.store.new_id("evt"),
            "object": "event",
            "api_version": self.store.metadata("api_version") or "2026-02-25.clover",
            "created": self.store.now(),
            "livemode": False,
            "pending_webhooks": 1 if self.options.webhook_url else 0,
            "type": event_type,
            "data": {"object": dict(source)},
        }
        self.delivery.record(event)

    def _deliver(self, event: Mapping[str, Any]) -> None:
        self.delivery.deliver(event)

    def wait_for_deliveries(self, timeout: float = 5) -> bool:
        return self.delivery.wait_for_idle(timeout)

    def reset(self) -> None:
        if not self.delivery.prepare_reset():
            raise SimulatorHTTPError(
                400,
                "simulator_busy",
                "Wait for the active webhook delivery before resetting",
            )
        self.store.reset()
        self._seed_catalog()

    def close(self) -> None:
        self.delivery.close()

    def _success_url(self, session: Mapping[str, Any]) -> str:
        return session["success_url"].replace("{CHECKOUT_SESSION_ID}", session["id"])

    def _state(self) -> dict[str, Any]:
        return {
            "clock": self.store.now(),
            "products": self.store.list("product"),
            "prices": self.store.list("price"),
            "customers": self.store.list("customer"),
            "checkout_sessions": self.store.list("checkout.session"),
            "subscriptions": self.store.list("subscription"),
            "invoices": self.store.list("invoice"),
            "events": self.store.events(),
        }

    def _home(self) -> str:
        state = self._state()
        customers = {customer["id"]: customer for customer in state["customers"]}
        invoices_by_subscription: dict[str, list[dict[str, Any]]] = {}
        for invoice in state["invoices"]:
            invoices_by_subscription.setdefault(invoice["subscription"], []).append(
                invoice
            )
        subscriptions: list[SubscriptionView] = []
        for subscription in state["subscriptions"]:
            customer = customers.get(subscription["customer"], {})
            invoices = invoices_by_subscription.get(subscription["id"], [])
            invoice = invoices[-1] if invoices else {}
            card = subscription["default_payment_method"]["card"]
            subscriptions.append(
                SubscriptionView(
                    id=subscription["id"],
                    customer_email=customer.get("email", ""),
                    status=subscription["status"],
                    period_end=self._format_time(subscription["current_period_end"]),
                    cancel_at_period_end=subscription["cancel_at_period_end"],
                    payment_method=(
                        card["brand"].title() + " ending in " + card["last4"]
                    ),
                    renewal_behavior=self.renewal_behavior(subscription["id"]),
                    invoice_id=invoice.get("id", ""),
                    invoice_status=invoice.get("status", ""),
                    invoice_attempts=int(invoice.get("attempt_count", 0)),
                )
            )
        events: list[EventView] = []
        for event in reversed(state["events"][-50:]):
            attempts = int(event["delivery_attempts"])
            payload = {
                name: value
                for name, value in event.items()
                if name
                not in {
                    "delivered",
                    "delivery_attempts",
                    "last_attempt_at",
                    "last_error",
                    "last_status",
                }
            }
            delivery = event["delivery_state"].replace("_", " ")
            last_response = ""
            if event["last_status"] is not None:
                last_response = "HTTP " + str(event["last_status"])
            elif event["last_error"]:
                last_response = event["last_error"]
            events.append(
                EventView(
                    id=event["id"],
                    type=event["type"],
                    created=self._format_time(event["created"]),
                    delivery=delivery,
                    attempts=attempts,
                    payload=json.dumps(payload, indent=2, sort_keys=True),
                    can_resend=bool(self.options.webhook_url),
                    last_response=last_response,
                    attempt_history=tuple(
                        self._format_attempt(attempt)
                        for attempt in self.store.delivery_attempts(event["id"])
                    ),
                )
            )
        invoices = tuple(
            InvoiceView(
                id=invoice["id"],
                subscription_id=invoice["subscription"],
                status=invoice["status"],
                billing_reason=invoice.get("billing_reason", ""),
                attempt_count=int(invoice.get("attempt_count", 0)),
                next_attempt=(
                    self._format_time(invoice["next_payment_attempt"])
                    if invoice.get("next_payment_attempt")
                    else ""
                ),
                error_code=(invoice.get("last_payment_error") or {}).get("code", ""),
            )
            for invoice in reversed(state["invoices"])
        )
        return simulator_document(
            DashboardView(
                clock=self._format_time(state["clock"]),
                api_base=self.options.public_url + "/v1",
                webhook_url=self.options.webhook_url,
                retry_policy=(
                    str(self.options.max_payment_attempts) + " payment attempts"
                ),
                customer_count=len(state["customers"]),
                subscription_count=len(state["subscriptions"]),
                invoice_count=len(state["invoices"]),
                delivery_mode=self.delivery.mode,
                pending_count=sum(
                    event["delivery_state"] in {"pending", "failed"}
                    for event in state["events"]
                ),
                subscriptions=tuple(subscriptions),
                invoices=invoices,
                events=tuple(events),
            )
        )

    @staticmethod
    def _format_time(timestamp: int) -> str:
        return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d %H:%M UTC")

    @classmethod
    def _format_attempt(cls, attempt: Mapping[str, Any]) -> str:
        result = cls._format_time(int(attempt["attempted_at"]))
        result += " · " + str(attempt["signature_mode"])
        if attempt["status"] is not None:
            result += " · HTTP " + str(attempt["status"])
        elif attempt["error"]:
            result += " · " + str(attempt["error"])
        return result

    @staticmethod
    def _document(title: str, body: str) -> str:
        return f"""<!doctype html>
        <html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{escape(title)}</title><style>
        body {{ background:#f6f9fc; color:#30313d; font:16px system-ui;
               margin:0; padding:3rem 1rem; }}
        main {{ background:white; border-radius:12px; box-shadow:0 7px 14px
                rgba(50,50,93,.1); margin:auto; max-width:460px; padding:2rem; }}
        h1 {{ margin:.25rem 0 1rem; }} .eyebrow {{ color:#635bff; font-weight:700; }}
        label {{ display:block; margin:1rem 0; }} input {{ box-sizing:border-box;
                 display:block; font:inherit; margin-top:.35rem; padding:.7rem;
                 width:100%; }} button {{ background:#635bff; border:0;
                 border-radius:6px; color:white; cursor:pointer; font:inherit;
                 font-weight:700; padding:.8rem 1rem; width:100%; }}
        a {{ color:#635bff; display:inline-block; margin-top:1rem; }}
        .error {{ color:#b42318; }} .hint {{ color:#697386; font-size:.85rem; }}
        .price {{ font-size:1.35rem; font-weight:700; }}
        </style></head><body>{body}</body></html>"""

    def _required(self, kind: str, object_id: str) -> dict[str, Any]:
        value = self.store.get(kind, object_id)
        if value is None:
            raise SimulatorHTTPError(
                404,
                "invalid_request_error",
                f"No such {kind}: '{object_id}'",
            )
        return value

    def _object(self, kind: str, object_id: str):
        return self._json(self._required(kind, object_id))

    def _list(self, kind: str) -> dict[str, Any]:
        return self._list_values(self.store.list(kind))

    @staticmethod
    def _list_values(values: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [dict(value) for value in values],
            "has_more": False,
            "url": "/v1",
        }

    @staticmethod
    def _nested(form: Mapping[str, str], prefix: str) -> dict[str, str]:
        start = prefix + "["
        return {
            key.removeprefix(start).removesuffix("]"): value
            for key, value in form.items()
            if key.startswith(start)
        }

    @staticmethod
    def _boolean(value: str) -> bool:
        return value.lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _query(environ) -> dict[str, str]:
        return {
            key: values[-1]
            for key, values in parse_qs(
                environ.get("QUERY_STRING", ""), keep_blank_values=True
            ).items()
        }

    @staticmethod
    def _form(environ) -> dict[str, str]:
        size = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(size).decode()
        return {
            key: values[-1]
            for key, values in parse_qs(body, keep_blank_values=True).items()
        }

    @staticmethod
    def _json(value: Mapping[str, Any], status: int = 200):
        body = json.dumps(dict(value), separators=(",", ":")).encode()
        return (
            f"{status} {status_text(status)}",
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Request-Id", "req_local"),
            ],
            body,
        )

    @classmethod
    def _html(cls, value: str, status: int = 200):
        body = value.encode()
        return (
            f"{status} {status_text(status)}",
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
            body,
        )

    @staticmethod
    def _redirect(url: str):
        return (
            "303 See Other",
            [("Location", url), ("Content-Length", "0")],
            b"",
        )


class SimulatorServer:
    """Start a simulator in a background thread for application tests."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        database: str | Path = ":memory:",
        webhook_url: str = "",
        webhook_secret: str = "whsec_local",
        api_key: str = "sk_test_local",
        product_id: str = "prod_local_membership",
        price_id: str = "price_local_monthly",
        product_name: str = "Example membership",
        unit_amount: int = 500,
        currency: str = "usd",
        max_payment_attempts: int = 3,
    ):
        self.store = SimulatorStore(database)
        self.development_app = Application(
            name="Local Stripe simulator",
        )
        self.httpd = Server(
            self.development_app,
            host=host,
            port=port,
            quiet=True,
        )
        public_url = self.httpd.url
        self.app = StripeSimulator(
            self.store,
            SimulatorOptions(
                public_url=public_url,
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
                api_key=api_key,
                product_id=product_id,
                price_id=price_id,
                product_name=product_name,
                unit_amount=unit_amount,
                currency=currency,
                max_payment_attempts=max_payment_attempts,
            ),
        )
        self.development_app.mount_wsgi(self.app)

    @property
    def url(self) -> str:
        return self.app.options.public_url

    def start(self) -> Self:
        self.httpd.start()
        return self

    def close(self) -> None:
        self.httpd.close()
        self.app.close()
        self.store.close()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *args: object) -> None:
        self.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12111)
    parser.add_argument("--database", default=".pyjs-stripe.sqlite3")
    parser.add_argument("--webhook-url", default="")
    parser.add_argument("--webhook-secret", default="whsec_local")
    parser.add_argument("--api-key", default="sk_test_local")
    parser.add_argument("--product-id", default="prod_local_membership")
    parser.add_argument("--price-id", default="price_local_monthly")
    parser.add_argument("--product-name", default="Example membership")
    parser.add_argument("--unit-amount", type=int, default=500)
    parser.add_argument("--currency", default="usd")
    parser.add_argument("--max-payment-attempts", type=int, default=3)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args(argv)
    store = SimulatorStore(args.database)
    development_app = Application(name="Local Stripe simulator")
    server = Server(
        development_app,
        host=args.host,
        port=args.port,
        allow_remote=args.allow_remote,
    )
    app = StripeSimulator(
        store,
        SimulatorOptions(
            public_url=server.url,
            webhook_url=args.webhook_url,
            webhook_secret=args.webhook_secret,
            api_key=args.api_key,
            product_id=args.product_id,
            price_id=args.price_id,
            product_name=args.product_name,
            unit_amount=args.unit_amount,
            currency=args.currency,
            max_payment_attempts=args.max_payment_attempts,
        ),
    )
    development_app.mount_wsgi(app)
    if args.webhook_url:
        print(f"Forwarding signed webhooks to {args.webhook_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        app.close()
        store.close()


if __name__ == "__main__":
    main()
