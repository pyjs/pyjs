import json
from http.client import HTTPConnection
from threading import Event, Lock, Thread
from urllib.parse import urlencode, urlsplit

from pyjs.server.dev import Application, Response, Server
from pyjs_extras.stripe.server import CheckoutRequest, StripeGateway
from pyjs_extras.stripe.simulator import SUCCESS_CARD, SimulatorServer


def post(url: str, values: dict[str, str]):
    parsed = urlsplit(url)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    connection.request(
        "POST",
        parsed.path,
        urlencode(values),
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    return connection, connection.getresponse()


def request_json(
    url: str,
    method: str,
    path: str,
    values: dict[str, str] | None = None,
):
    parsed = urlsplit(url)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    body = urlencode(values) if values is not None else None
    headers = (
        {"Content-Type": "application/x-www-form-urlencoded"}
        if values is not None
        else {}
    )
    connection.request(method, path, body, headers)
    response = connection.getresponse()
    try:
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def get(url: str):
    parsed = urlsplit(url)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    connection.request("GET", parsed.path or "/")
    return connection, connection.getresponse()


def test_official_sdk_drives_stateful_subscription_workflow():
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        checkout = gateway.create_checkout(
            CheckoutRequest(
                price_id="price_local_monthly",
                success_url=("http://app.test/success?session_id={CHECKOUT_SESSION_ID}"),
                cancel_url="http://app.test/cancel",
                customer_email="member@example.com",
            )
        )

        connection, response = post(
            checkout.url + "/complete",
            {"card_number": SUCCESS_CARD},
        )
        try:
            assert response.status == 303
            assert response.getheader("Location", "").endswith(
                f"?session_id={checkout.id}"
            )
        finally:
            response.read()
            connection.close()

        customer = simulator.store.list("customer")[0]
        subscription = simulator.store.list("subscription")[0]
        invoice = simulator.store.list("invoice")[0]
        assert customer["email"] == "member@example.com"
        assert subscription["status"] == "active"
        assert invoice["attempted"] is True

        portal = gateway.create_portal(
            customer["id"],
            "http://app.test/membership/",
        )
        connection, response = post(portal.url + "/cancel", {})
        try:
            assert response.status == 303
        finally:
            response.read()
            connection.close()
        assert simulator.store.list("subscription")[0]["cancel_at_period_end"]


def test_operator_dashboard_drives_failed_renewal_and_recovery():
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        checkout = gateway.create_checkout(
            CheckoutRequest(
                price_id="price_local_monthly",
                success_url="http://app.test/success",
                cancel_url="http://app.test/cancel",
                customer_email="member@example.com",
            )
        )
        connection, response = post(
            checkout.url + "/complete",
            {"card_number": SUCCESS_CARD},
        )
        response.read()
        connection.close()
        subscription_id = simulator.store.list("subscription")[0]["id"]

        connection, response = get(simulator.url)
        source = response.read().decode()
        connection.close()
        assert response.status == 200
        assert "Local Stripe simulator" in source
        assert "member@example.com" in source

        connection, response = post(
            simulator.url + f"/_simulator/subscriptions/{subscription_id}/behavior",
            {"behavior": "soft_decline"},
        )
        response.read()
        connection.close()
        assert response.status == 303
        connection, response = post(
            simulator.url + f"/_simulator/subscriptions/{subscription_id}/renew",
            {},
        )
        response.read()
        connection.close()
        assert response.status == 303
        assert simulator.store.list("subscription")[0]["status"] == "past_due"
        assert simulator.store.list("invoice")[-1]["status"] == "open"

        connection, response = post(
            simulator.url + f"/_simulator/subscriptions/{subscription_id}/behavior",
            {"behavior": "success"},
        )
        response.read()
        connection.close()
        connection, response = post(
            simulator.url + f"/_simulator/subscriptions/{subscription_id}/retry",
            {},
        )
        response.read()
        connection.close()
        assert response.status == 303
        assert simulator.store.list("subscription")[0]["status"] == "active"
        invoice = simulator.store.list("invoice")[-1]
        assert invoice["status"] == "paid"
        assert invoice["attempt_count"] == 2


def test_retry_policy_and_payment_replacement_cover_terminal_states():
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        checkout = gateway.create_checkout(
            CheckoutRequest(
                "price_local_monthly",
                "http://app.test/success",
                "http://app.test/cancel",
            )
        )
        connection, response = post(
            checkout.url + "/complete",
            {"card_number": SUCCESS_CARD},
        )
        response.read()
        connection.close()
        subscription_id = simulator.store.list("subscription")[0]["id"]
        simulator.app.set_renewal_behavior(subscription_id, "soft_decline")

        simulator.app.advance_clock(30)
        simulator.app.advance_clock(1)
        simulator.app.advance_clock(3)

        subscription = simulator.store.list("subscription")[0]
        invoice = simulator.store.list("invoice")[-1]
        assert subscription["status"] == "unpaid"
        assert invoice["status"] == "uncollectible"
        assert invoice["attempt_count"] == 3

        simulator.app.replace_payment_method(
            subscription_id,
            SUCCESS_CARD,
            retry=False,
        )
        subscription = simulator.store.list("subscription")[0]
        assert subscription["default_payment_method"]["card"]["last4"] == "4242"


def test_slow_webhook_delivery_does_not_block_the_api():
    received = Event()
    release = Event()

    sink_application = Application(name="Stripe webhook sink")
    blocked = False

    @sink_application.post("/webhook")
    def accept_webhook(request):
        nonlocal blocked
        if not blocked:
            blocked = True
            received.set()
            release.wait(timeout=5)
        return Response.text("ok")

    sink = Server(sink_application, port=0, quiet=True)
    sink.start()
    try:
        with SimulatorServer(
            webhook_url=f"{sink.url}/webhook",
        ) as simulator:
            gateway = StripeGateway("sk_test_local", api_base=simulator.url)
            checkout = gateway.create_checkout(
                CheckoutRequest(
                    "price_local_monthly",
                    "http://app.test/success",
                    "http://app.test/cancel",
                )
            )

            def complete_checkout():
                connection, response = post(
                    checkout.url + "/complete",
                    {"card_number": SUCCESS_CARD},
                )
                response.read()
                connection.close()

            completion = Thread(
                target=complete_checkout,
                daemon=True,
            )
            completion.start()
            assert received.wait(timeout=2)

            parsed = urlsplit(simulator.url)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            connection.request("GET", "/_test/state")
            response = connection.getresponse()
            assert response.status == 200
            response.read()
            connection.close()

            release.set()
            completion.join(timeout=5)
            assert not completion.is_alive()
            assert simulator.app.wait_for_deliveries(timeout=5)
    finally:
        release.set()
        sink.close()


def test_manual_delivery_does_not_repeat_queued_automatic_events():
    received: list[str] = []
    first_received = Event()
    release_first = Event()

    sink_application = Application(name="Stripe webhook sink")

    @sink_application.post("/webhook")
    def accept_webhook(request):
        received.append(request.json()["id"])
        if len(received) == 1:
            first_received.set()
            release_first.wait(timeout=5)
        return Response.text("ok")

    sink = Server(sink_application, port=0, quiet=True).start()
    try:
        with SimulatorServer(webhook_url=f"{sink.url}/webhook") as simulator:
            gateway = StripeGateway("sk_test_local", api_base=simulator.url)
            checkout = gateway.create_checkout(
                CheckoutRequest(
                    "price_local_monthly",
                    "http://app.test/success",
                    "http://app.test/cancel",
                )
            )
            connection, response = post(
                checkout.url + "/complete",
                {"card_number": SUCCESS_CARD},
            )
            response.read()
            connection.close()
            assert first_received.wait(timeout=2)

            simulator.app.delivery.set_mode("manual")
            release_first.set()
            assert simulator.app.wait_for_deliveries(timeout=5)
            simulator.app._deliver_pending("newest")
            event_ids = [event["id"] for event in simulator.store.events()]
            expected_delivery = event_ids[:1] + list(reversed(event_ids[1:]))
            assert received == expected_delivery

            simulator.app.delivery.set_mode("automatic")
            assert simulator.app.wait_for_deliveries(timeout=5)
            assert received == expected_delivery
    finally:
        release_first.set()
        sink.close()


def test_concurrent_renewals_advance_distinct_billing_periods():
    with SimulatorServer() as simulator:
        gateway = StripeGateway("sk_test_local", api_base=simulator.url)
        checkout = gateway.create_checkout(
            CheckoutRequest(
                "price_local_monthly",
                "http://app.test/success",
                "http://app.test/cancel",
            )
        )
        connection, response = post(
            checkout.url + "/complete",
            {"card_number": SUCCESS_CARD},
        )
        response.read()
        connection.close()
        subscription = simulator.store.list("subscription")[0]
        subscription_id = subscription["id"]
        initial_period_end = subscription["current_period_end"]

        first_read = Event()
        second_read = Event()
        read_lock = Lock()
        invoice_reads = 0
        original_list = simulator.store.list

        def coordinated_list(kind: str):
            nonlocal invoice_reads
            value = original_list(kind)
            if kind != "invoice":
                return value
            with read_lock:
                invoice_reads += 1
                read_number = invoice_reads
            if read_number == 1:
                first_read.set()
                second_read.wait(timeout=0.2)
            elif read_number == 2:
                second_read.set()
            return value

        simulator.store.list = coordinated_list
        paths = [
            f"/_simulator/subscriptions/{subscription_id}/renew",
            f"/_simulator/subscriptions/{subscription_id}/renew",
        ]
        responses: list[int] = []

        def renew(path: str) -> None:
            connection, response = post(simulator.url + path, {})
            responses.append(response.status)
            response.read()
            connection.close()

        workers = [Thread(target=renew, args=(path,)) for path in paths]
        for worker in workers:
            worker.start()
        assert first_read.wait(timeout=2)
        for worker in workers:
            worker.join(timeout=5)
            assert not worker.is_alive()

        assert responses == [303, 303]
        invoices = simulator.store.list("invoice")
        assert len(invoices) == 3
        assert invoices[1]["period_start"] == initial_period_end
        assert invoices[2]["period_start"] == invoices[1]["period_end"]


def test_malformed_simulator_requests_return_structured_errors():
    with SimulatorServer() as simulator:
        status, value = request_json(
            simulator.url,
            "POST",
            "/_test/clock/advance",
            {"days": "tomorrow"},
        )
        assert status == 400
        assert value == {
            "error": {
                "type": "invalid_request_error",
                "message": "days must be an integer",
            }
        }

        status, value = request_json(
            simulator.url,
            "POST",
            "/portal/incomplete",
            {},
        )
        assert status == 404
        assert value == {
            "error": {
                "type": "invalid_request_error",
                "message": "No such endpoint",
            }
        }

        status, value = request_json(simulator.url, "GET", "/_test/state")
        assert status == 200
        assert "clock" in value
