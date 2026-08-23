from pyjs_extras.stripe.server import CheckoutRequest, PaymentRequest
from pyjs_extras.stripe.testing import MockStripeGateway


def test_mock_checkout_and_portal_scenario():
    store = {}
    gateway = MockStripeGateway(store, "https://app.test")
    checkout = gateway.create_checkout(
        CheckoutRequest(
            "price_monthly",
            "https://app.test/success",
            "https://app.test/cancel",
            client_reference_id="42",
            customer_email="member@example.com",
        )
    )

    assert checkout.url.startswith("https://app.test/stripe/mock/checkout/")
    subscription = gateway.complete_checkout(checkout.id)
    assert subscription.status == "active"
    assert subscription.payment_method_last4 == "4242"
    assert gateway.complete_checkout(checkout.id) == subscription

    portal = gateway.create_portal(
        subscription.customer_id,
        "https://app.test/account",
    )
    assert portal.url.startswith("https://app.test/stripe/mock/portal/")
    canceled = gateway.set_cancel_at_period_end(subscription.id, True)
    assert canceled.cancel_at_period_end
    assert gateway.subscription(subscription.id) == canceled


def test_mock_one_time_payment_creation_and_completion_are_idempotent():
    gateway = MockStripeGateway({}, "https://app.test")
    request = PaymentRequest(
        8800,
        "Northstar order #1",
        "https://app.test/account",
        "https://app.test/",
        idempotency_key="northstar-order-1",
        metadata={"order_id": "1"},
    )
    checkout = gateway.create_payment(request)

    assert gateway.create_payment(request) == checkout

    payment = gateway.complete_payment(checkout.id)

    assert payment.amount_cents == 8800
    assert payment.status == "succeeded"
    assert gateway.complete_payment(checkout.id) == payment
    assert gateway.checkout(checkout.id)["payment_status"] == "paid"
