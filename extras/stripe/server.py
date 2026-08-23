"""Framework-neutral server adapter for the official Stripe Python SDK."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class CheckoutRequest:
    """Values needed to create a hosted Stripe Checkout subscription."""

    price_id: str
    success_url: str
    cancel_url: str
    client_reference_id: str = ""
    customer_id: str = ""
    customer_email: str = ""
    quantity: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentRequest:
    """Values needed to create a one-time hosted Stripe Checkout payment."""

    amount_cents: int
    name: str
    success_url: str
    cancel_url: str
    currency: str = "usd"
    client_reference_id: str = ""
    customer_email: str = ""
    idempotency_key: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HostedSession:
    id: str
    kind: Literal["checkout", "portal"]
    url: str


@dataclass(frozen=True)
class WebhookEvent:
    id: str
    type: str
    data: object
    created: int = 0


class StripeClientProtocol(Protocol):
    v1: Any

    def construct_event(
        self,
        payload: bytes | str,
        signature: str,
        secret: str,
    ) -> Any: ...


def _new_client(
    secret_key: str,
    max_network_retries: int,
    api_base: str,
) -> StripeClientProtocol:
    try:
        from stripe import StripeClient
    except ImportError as error:
        raise RuntimeError(
            "Stripe server support requires `pyjs-extras[stripe]`."
        ) from error
    options: dict[str, object] = {
        "max_network_retries": max_network_retries,
    }
    if api_base:
        options["base_addresses"] = {"api": api_base.rstrip("/")}
    return StripeClient(secret_key, **options)


class StripeGateway:
    """Small stable facade over the generated Stripe SDK service tree."""

    def __init__(
        self,
        secret_key: str,
        *,
        webhook_secret: str = "",
        api_base: str = "",
        max_network_retries: int = 2,
        client: StripeClientProtocol | None = None,
    ):
        if not secret_key and client is None:
            raise ValueError("a Stripe secret key is required")
        self.client = client or _new_client(
            secret_key,
            max_network_retries,
            api_base,
        )
        self.webhook_secret = webhook_secret

    def create_checkout(self, request: CheckoutRequest) -> HostedSession:
        params: dict[str, object] = {
            "mode": "subscription",
            "line_items": [{"price": request.price_id, "quantity": request.quantity}],
            "success_url": request.success_url,
            "cancel_url": request.cancel_url,
        }
        if request.client_reference_id:
            params["client_reference_id"] = request.client_reference_id
        if request.customer_id:
            params["customer"] = request.customer_id
        elif request.customer_email:
            params["customer_email"] = request.customer_email
        if request.metadata:
            params["metadata"] = dict(request.metadata)
            params["subscription_data"] = {"metadata": dict(request.metadata)}
        session = self.client.v1.checkout.sessions.create(params)
        return HostedSession(session.id, "checkout", session.url)

    def create_payment(self, request: PaymentRequest) -> HostedSession:
        if request.amount_cents < 1:
            raise ValueError("a positive payment amount is required")
        params: dict[str, object] = {
            "mode": "payment",
            "line_items": [
                {
                    "price_data": {
                        "currency": request.currency,
                        "product_data": {"name": request.name},
                        "unit_amount": request.amount_cents,
                    },
                    "quantity": 1,
                }
            ],
            "success_url": request.success_url,
            "cancel_url": request.cancel_url,
        }
        if request.client_reference_id:
            params["client_reference_id"] = request.client_reference_id
        if request.customer_email:
            params["customer_email"] = request.customer_email
        if request.metadata:
            params["metadata"] = dict(request.metadata)
        if request.idempotency_key:
            session = self.client.v1.checkout.sessions.create(
                params,
                options={"idempotency_key": request.idempotency_key},
            )
        else:
            session = self.client.v1.checkout.sessions.create(params)
        return HostedSession(session.id, "checkout", session.url)

    def create_portal(
        self,
        customer_id: str,
        return_url: str,
    ) -> HostedSession:
        if not customer_id:
            raise ValueError("a Stripe customer ID is required")
        session = self.client.v1.billing_portal.sessions.create(
            {"customer": customer_id, "return_url": return_url}
        )
        return HostedSession(session.id, "portal", session.url)

    def construct_event(
        self,
        payload: bytes | str,
        signature: str,
    ) -> WebhookEvent:
        if not self.webhook_secret:
            raise ValueError("a Stripe webhook secret is required")
        event = self.client.construct_event(
            payload,
            signature,
            self.webhook_secret,
        )
        return WebhookEvent(
            event.id,
            event.type,
            event.data.object,
            int(getattr(event, "created", 0)),
        )
