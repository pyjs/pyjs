import hashlib
import hmac
import json
import sqlite3
import time
from threading import Event, Thread

import pytest
from pyjs.server.dev import Application, Response, Server
from pyjs_extras.stripe.simulator_delivery import WebhookDelivery
from pyjs_extras.stripe.simulator_store import SimulatorStore


@pytest.fixture
def webhook_sink():
    accepted: list[str] = []
    application = Application(name="Stripe webhook sink")

    @application.post("/webhook")
    def receive(request):
        signature = {
            name: value
            for name, value in (
                part.split("=", 1)
                for part in request.headers["Stripe-Signature"].split(",")
            )
        }
        timestamp = int(signature["t"])
        signed = str(timestamp).encode() + b"." + request.body
        digest = hmac.new(b"whsec_local", signed, hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(digest, signature["v1"])
        valid = valid and abs(int(time.time()) - timestamp) <= 300
        if valid:
            accepted.append(json.loads(request.body)["id"])
        return Response.text("ok", status=200 if valid else 400)

    server = Server(application, port=0, quiet=True).start()
    try:
        yield server.url + "/webhook", accepted
    finally:
        server.close()


def event(event_id: str) -> dict[str, object]:
    return {
        "id": event_id,
        "object": "event",
        "type": "invoice.paid",
        "data": {"object": {"id": "in_local"}},
    }


def test_existing_database_adds_delivery_metadata(tmp_path):
    database = tmp_path / "stripe.sqlite3"
    connection = sqlite3.connect(database)
    with connection:
        connection.execute(
            """
            CREATE TABLE events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                delivered INTEGER NOT NULL DEFAULT 0
            )
            """
        )
    connection.close()

    store = SimulatorStore(database)
    try:
        store.add_event(event("evt_existing"), pending=True)
        store.event_attempt(
            "evt_existing",
            True,
            signature_mode="valid",
            status=200,
            error="",
        )
        stored = store.events()[0]
        assert stored["delivery_state"] == "delivered"
        assert stored["last_status"] == 200
        assert stored["last_error"] == ""
        assert stored["last_attempt_at"] is not None
    finally:
        store.close()


def test_signature_variants_retain_every_delivery_attempt(webhook_sink):
    url, accepted = webhook_sink
    store = SimulatorStore()
    delivery = WebhookDelivery(store, url, "whsec_local")
    try:
        value = event("evt_signatures")
        delivery.record(value)
        assert delivery.wait_for_idle()
        assert delivery.deliver(value, signature_mode="invalid") is False
        assert delivery.deliver(value, signature_mode="stale") is False

        attempts = store.delivery_attempts("evt_signatures")
        assert [attempt["signature_mode"] for attempt in attempts] == [
            "valid",
            "invalid",
            "stale",
        ]
        assert [attempt["status"] for attempt in attempts] == [200, 400, 400]
        assert accepted == ["evt_signatures"]
    finally:
        delivery.close()
        store.close()


def test_idle_wait_includes_manual_delivery_attempts():
    received = Event()
    release = Event()
    application = Application(name="Stripe webhook sink")

    @application.post("/webhook")
    def receive(request):
        received.set()
        release.wait(timeout=5)
        return Response.text("ok")

    server = Server(application, port=0, quiet=True).start()
    store = SimulatorStore()
    delivery = WebhookDelivery(store, server.url + "/webhook", "whsec_local")
    delivery.set_mode("manual")
    value = event("evt_manual")
    delivery.record(value)
    worker = Thread(target=delivery.deliver, args=(value,))
    worker.start()
    try:
        assert received.wait(timeout=2)
        assert delivery.wait_for_idle(timeout=0.01) is False
        release.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert delivery.wait_for_idle()
    finally:
        release.set()
        delivery.close()
        store.close()
        server.close()


def test_pending_events_and_manual_mode_survive_restart(tmp_path, webhook_sink):
    url, accepted = webhook_sink
    database = tmp_path / "stripe.sqlite3"
    store = SimulatorStore(database)
    delivery = WebhookDelivery(store, url, "whsec_local")
    delivery.set_mode("manual")
    delivery.record(event("evt_first"))
    delivery.record(event("evt_second"))
    delivery.close()
    store.close()
    assert accepted == []

    store = SimulatorStore(database)
    delivery = WebhookDelivery(store, url, "whsec_local")
    try:
        assert delivery.mode == "manual"
        assert [value["delivery_state"] for value in store.events()] == [
            "pending",
            "pending",
        ]
        delivery.set_mode("automatic")
        assert delivery.wait_for_idle()
        assert accepted == ["evt_first", "evt_second"]
    finally:
        delivery.close()
        store.close()
