from types import SimpleNamespace

import pytest
from pyjs_extras.stripe.server import CheckoutRequest, PaymentRequest, StripeGateway


class Service:
    def __init__(self, result):
        self.result = result
        self.params = None
        self.options = None

    def create(self, params, options=None):
        self.params = params
        self.options = options
        return self.result


class Client:
    def __init__(self):
        self.checkout = Service(
            SimpleNamespace(id="cs_test", url="https://checkout.test/session")
        )
        self.portal = Service(
            SimpleNamespace(id="bps_test", url="https://portal.test/session")
        )
        self.v1 = SimpleNamespace(
            checkout=SimpleNamespace(sessions=self.checkout),
            billing_portal=SimpleNamespace(sessions=self.portal),
        )
        self.event_args = None

    def construct_event(self, *args):
        self.event_args = args
        return SimpleNamespace(
            id="evt_test",
            type="checkout.session.completed",
            data=SimpleNamespace(object={"id": "cs_test"}),
        )


def test_checkout_uses_customer_email_until_customer_is_known():
    client = Client()
    gateway = StripeGateway("", client=client)

    session = gateway.create_checkout(
        CheckoutRequest(
            price_id="price_monthly",
            success_url="https://app.test/success",
            cancel_url="https://app.test/cancel",
            client_reference_id="42",
            customer_email="member@example.com",
        )
    )

    assert session.id == "cs_test"
    assert session.kind == "checkout"
    assert client.checkout.params == {
        "mode": "subscription",
        "line_items": [{"price": "price_monthly", "quantity": 1}],
        "success_url": "https://app.test/success",
        "cancel_url": "https://app.test/cancel",
        "client_reference_id": "42",
        "customer_email": "member@example.com",
    }


def test_checkout_prefers_existing_customer():
    client = Client()
    gateway = StripeGateway("", client=client)

    gateway.create_checkout(
        CheckoutRequest(
            "price_monthly",
            "https://app.test/success",
            "https://app.test/cancel",
            customer_id="cus_test",
            customer_email="ignored@example.com",
        )
    )

    assert client.checkout.params["customer"] == "cus_test"
    assert "customer_email" not in client.checkout.params


def test_one_time_payment_uses_inline_price_data():
    client = Client()
    gateway = StripeGateway("", client=client)

    session = gateway.create_payment(
        PaymentRequest(
            12900,
            "Northstar order #42",
            "https://app.test/success",
            "https://app.test/cancel",
            customer_email="shopper@example.com",
            idempotency_key="northstar-order-42",
            metadata={"order_id": "42"},
        )
    )

    assert session.id == "cs_test"
    assert client.checkout.params == {
        "mode": "payment",
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Northstar order #42"},
                    "unit_amount": 12900,
                },
                "quantity": 1,
            }
        ],
        "success_url": "https://app.test/success",
        "cancel_url": "https://app.test/cancel",
        "customer_email": "shopper@example.com",
        "metadata": {"order_id": "42"},
    }
    assert client.checkout.options == {
        "idempotency_key": "northstar-order-42"
    }


def test_portal_requires_customer_and_returns_hosted_session():
    client = Client()
    gateway = StripeGateway("", client=client)

    with pytest.raises(ValueError, match="customer ID"):
        gateway.create_portal("", "https://app.test/account")

    session = gateway.create_portal("cus_test", "https://app.test/account")
    assert session.kind == "portal"
    assert client.portal.params == {
        "customer": "cus_test",
        "return_url": "https://app.test/account",
    }


def test_webhook_verification_is_required_and_adapted():
    client = Client()
    gateway = StripeGateway("", client=client)
    with pytest.raises(ValueError, match="webhook secret"):
        gateway.construct_event(b"{}", "signature")

    gateway = StripeGateway(
        "",
        client=client,
        webhook_secret="whsec_test",
    )
    event = gateway.construct_event(b"{}", "signature")
    assert event.id == "evt_test"
    assert event.data == {"id": "cs_test"}
    assert event.created == 0
    assert client.event_args == (b"{}", "signature", "whsec_test")
