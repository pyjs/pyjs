import pytest
from pyjs_extras.stripe.server import CheckoutRequest, StripeGateway
from pyjs_extras.stripe.simulator import SUCCESS_CARD, SimulatorServer
from test_simulator import get, post

from stripe import InvalidRequestError


def checkout(gateway):
    return gateway.create_checkout(CheckoutRequest(
        price_id="price_local_monthly", success_url="http://example.test/account",
        cancel_url="http://example.test/account", customer_email="subscriber@example.test",
    ))


def complete(session):
    connection, response = post(session.url + "/complete", {"card_number": SUCCESS_CARD})
    try:
        assert response.status == 303
        response.read()
    finally:
        connection.close()


@pytest.mark.parametrize("clock", [False, True])
def test_expired_sessions_cannot_charge_or_authenticate(clock):
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        session = checkout(gateway)
        if clock:
            simulator.app.advance_clock(1)
        else:
            expired = gateway.client.v1.checkout.sessions.expire(session.id)
            assert expired.status == "expired" and expired.url is None
        assert gateway.client.v1.checkout.sessions.retrieve(session.id).status == "expired"
        connection, response = get(session.url)
        try:
            assert response.status == 410
            assert b"Checkout expired" in response.read()
        finally:
            connection.close()
        for action in ("complete", "authenticate"):
            connection, response = post(session.url + "/" + action, {"card_number": SUCCESS_CARD})
            try:
                assert response.status == 400
                response.read()
            finally:
                connection.close()
        assert simulator.store.list("subscription") == []
        assert simulator.store.list("invoice") == []
        assert len(simulator.store.events()) == 1


def test_expire_idempotency_and_completed_session_rejection():
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        first = checkout(gateway)
        client = gateway.client.v1.checkout.sessions
        client.expire(first.id, options={"idempotency_key": "expiry-request"})
        assert client.expire(first.id, options={"idempotency_key": "expiry-request"}).status == "expired"
        assert len(simulator.store.events()) == 1
        with pytest.raises(InvalidRequestError):
            client.expire(first.id)
        second = checkout(gateway)
        complete(second)
        with pytest.raises(InvalidRequestError):
            client.expire(second.id)


def test_invoice_sdk_pagination_filters_and_lookup():
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        complete(checkout(gateway))
        first = simulator.store.list("subscription")[0]
        simulator.app.renew_subscription(first["id"])
        simulator.app.renew_subscription(first["id"])
        complete(checkout(gateway))
        invoices = gateway.client.v1.invoices
        parameters = {"customer": first["customer"], "status": "paid", "limit": 2}
        page = invoices.list(parameters)
        assert len(page.data) == 2 and page.has_more
        second = invoices.list({**parameters, "starting_after": page.data[-1].id})
        assert len(second.data) == 1 and not second.has_more
        ids = [item.id for item in (*page.data, *second.data)]
        assert len(set(ids)) == 3
        assert invoices.retrieve(ids[0]).customer == first["customer"]
        assert invoices.list({"customer": "missing"}).data == []
        assert invoices.list({"customer": first["customer"], "status": "open"}).data == []
        with pytest.raises(InvalidRequestError):
            invoices.list({"limit": 0})
        with pytest.raises(InvalidRequestError):
            invoices.list({"starting_after": "missing"})


@pytest.mark.parametrize("parameters, field", [
    ({"created": {"gte": 9999999999}}, "created[gte]"),
    ({"collection_method": "send_invoice"}, "collection_method"),
    ({"due_date": {"lte": 1}}, "due_date[lte]"),
    ({"expand": ["data.customer"]}, "expand[0]"),
])
def test_invoice_list_rejects_unsupported_options(parameters, field):
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        complete(checkout(gateway))
        with pytest.raises(InvalidRequestError) as error:
            gateway.client.v1.invoices.list(parameters)
        assert error.value.http_status == 400
        assert error.value.user_message == f"Unsupported invoice list parameter: {field}"
        assert len(gateway.client.v1.invoices.list().data) == 1


def test_checkout_expiry_validation_and_invoice_uses_selected_price():
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        now = simulator.store.now()
        params = {"mode": "subscription", "line_items": [{"price": "price_local_monthly", "quantity": 1}],
                  "success_url": "http://example.test/account", "cancel_url": "http://example.test/account"}
        for expires_at in (now, now + 86401):
            with pytest.raises(InvalidRequestError):
                gateway.client.v1.checkout.sessions.create({**params, "expires_at": expires_at})
        session = gateway.client.v1.checkout.sessions.create({**params, "expires_at": now + 1800})
        assert session.expires_at == now + 1800
        price = simulator.store.list("price")[0]
        simulator.store.put("price", {**price, "unit_amount": 900})
        complete(session)
        assert gateway.client.v1.invoices.list().data[0].amount_paid == 900
