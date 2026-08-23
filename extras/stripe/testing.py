"""Deterministic Stripe substitute for application and browser tests."""

from collections.abc import MutableMapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Any, Literal

from .server import CheckoutRequest, HostedSession, PaymentRequest


@dataclass(frozen=True)
class MockSubscription:
    id: str
    customer_id: str
    price_id: str
    current_period_end: str
    status: Literal["active", "canceled"] = "active"
    cancel_at_period_end: bool = False
    payment_method_brand: str = "visa"
    payment_method_last4: str = "4242"


@dataclass(frozen=True)
class MockPayment:
    id: str
    checkout_session_id: str
    amount_cents: int
    currency: str
    status: Literal["succeeded"] = "succeeded"


def _id(prefix: str) -> str:
    return f"{prefix}_mock_{token_urlsafe(12)}"


class MockStripeGateway:
    """Stateful mock with hosted URLs that an application can route locally."""

    def __init__(
        self,
        store: MutableMapping[str, Any],
        base_url: str,
        *,
        state_key: str = "pyjs_extras_mock_stripe",
        route_prefix: str = "/stripe/mock",
    ):
        self.store = store
        self.base_url = base_url.rstrip("/")
        self.state_key = state_key
        self.route_prefix = "/" + route_prefix.strip("/")

    @property
    def state(self) -> dict[str, Any]:
        return self.store.setdefault(
            self.state_key,
            {
                "checkout_sessions": {},
                "portal_sessions": {},
                "payments": {},
                "subscriptions": {},
                "payment_idempotency": {},
            },
        )

    def save(self) -> None:
        self.store[self.state_key] = self.state
        if hasattr(self.store, "modified"):
            self.store.modified = True

    def create_checkout(self, request: CheckoutRequest) -> HostedSession:
        session_id = _id("cs")
        self.state["checkout_sessions"][session_id] = {
            "id": session_id,
            "client_reference_id": request.client_reference_id,
            "customer_email": request.customer_email,
            "metadata": dict(request.metadata),
            "price_id": request.price_id,
            "status": "open",
            "payment_status": "unpaid",
        }
        self.save()
        return HostedSession(
            session_id,
            "checkout",
            f"{self.base_url}{self.route_prefix}/checkout/{session_id}/",
        )

    def checkout(self, session_id: str) -> dict[str, Any] | None:
        return self.state["checkout_sessions"].get(session_id)

    def create_payment(self, request: PaymentRequest) -> HostedSession:
        if request.amount_cents < 1:
            raise ValueError("a positive payment amount is required")
        idempotency = self.state.setdefault("payment_idempotency", {})
        if request.idempotency_key:
            existing_id = idempotency.get(request.idempotency_key)
            if existing_id is not None:
                return HostedSession(
                    existing_id,
                    "checkout",
                    f"{self.base_url}{self.route_prefix}/checkout/{existing_id}/",
                )
        session_id = _id("cs")
        self.state["checkout_sessions"][session_id] = {
            "id": session_id,
            "amount_cents": request.amount_cents,
            "client_reference_id": request.client_reference_id,
            "currency": request.currency,
            "customer_email": request.customer_email,
            "metadata": dict(request.metadata),
            "name": request.name,
            "mode": "payment",
            "status": "open",
            "payment_status": "unpaid",
        }
        if request.idempotency_key:
            idempotency[request.idempotency_key] = session_id
        self.save()
        return HostedSession(
            session_id,
            "checkout",
            f"{self.base_url}{self.route_prefix}/checkout/{session_id}/",
        )

    def complete_payment(self, session_id: str) -> MockPayment:
        checkout = self.checkout(session_id)
        if checkout is None or checkout.get("mode") != "payment":
            raise KeyError(session_id)
        existing_id = checkout.get("payment")
        if existing_id:
            return MockPayment(**self.state["payments"][existing_id])
        payment = MockPayment(
            id=_id("py"),
            checkout_session_id=session_id,
            amount_cents=checkout["amount_cents"],
            currency=checkout["currency"],
        )
        checkout.update(
            {
                "payment": payment.id,
                "status": "complete",
                "payment_status": "paid",
            }
        )
        self.state["payments"][payment.id] = asdict(payment)
        self.save()
        return payment

    def complete_checkout(self, session_id: str) -> MockSubscription:
        checkout = self.checkout(session_id)
        if checkout is None:
            raise KeyError(session_id)
        existing_id = checkout.get("subscription")
        if existing_id:
            return MockSubscription(**self.state["subscriptions"][existing_id])
        customer_id = _id("cus")
        subscription = MockSubscription(
            id=_id("sub"),
            customer_id=customer_id,
            price_id=checkout["price_id"],
            current_period_end=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
        )
        checkout.update(
            {
                "customer": customer_id,
                "subscription": subscription.id,
                "status": "complete",
                "payment_status": "paid",
            }
        )
        self.state["subscriptions"][subscription.id] = asdict(subscription)
        self.save()
        return subscription

    def create_portal(
        self,
        customer_id: str,
        return_url: str,
    ) -> HostedSession:
        if not customer_id:
            raise ValueError("a Stripe customer ID is required")
        session_id = _id("bps")
        self.state["portal_sessions"][session_id] = {
            "id": session_id,
            "customer": customer_id,
            "return_url": return_url,
        }
        self.save()
        return HostedSession(
            session_id,
            "portal",
            f"{self.base_url}{self.route_prefix}/portal/{session_id}/",
        )

    def portal(self, session_id: str) -> dict[str, Any] | None:
        return self.state["portal_sessions"].get(session_id)

    def subscription(self, subscription_id: str) -> MockSubscription | None:
        value = self.state["subscriptions"].get(subscription_id)
        return MockSubscription(**value) if value else None

    def latest_subscription(self) -> MockSubscription | None:
        subscriptions = self.state["subscriptions"]
        if not subscriptions:
            return None
        subscription_id = next(reversed(subscriptions))
        return self.subscription(subscription_id)

    def set_cancel_at_period_end(
        self,
        subscription_id: str,
        value: bool,
    ) -> MockSubscription:
        subscription = self.subscription(subscription_id)
        if subscription is None:
            raise KeyError(subscription_id)
        updated = MockSubscription(
            **{
                **asdict(subscription),
                "cancel_at_period_end": value,
            }
        )
        self.state["subscriptions"][subscription_id] = asdict(updated)
        self.save()
        return updated
