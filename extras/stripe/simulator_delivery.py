"""Deterministic webhook delivery for the local Stripe simulator."""

import hashlib
import hmac
import json
import threading
import time
from collections import deque
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .simulator_store import SimulatorStore

DELIVERY_MODES = {"automatic", "manual", "paused"}
SIGNATURE_MODES = {"valid", "invalid", "stale"}


class WebhookDelivery:
    """Record events and forward them without blocking simulator requests."""

    def __init__(self, store: SimulatorStore, url: str, secret: str):
        self.store = store
        self.url = url
        self.secret = secret
        self._condition = threading.Condition()
        self._queue: deque[tuple[str, str]] = deque()
        self._queued: set[str] = set()
        self._active_deliveries = 0
        self._closed = False
        self._worker = threading.Thread(
            target=self._work,
            name="pyjs-stripe-webhooks",
            daemon=True,
        )
        self._worker.start()
        if self.mode == "automatic":
            self.enqueue_pending()

    @property
    def mode(self) -> str:
        return self.store.metadata("delivery_mode") or "automatic"

    def set_mode(self, mode: str) -> None:
        if mode not in DELIVERY_MODES:
            raise ValueError(f"Unsupported delivery mode: {mode}")
        with self._condition:
            self.store.set_metadata("delivery_mode", mode)
            if mode == "manual":
                self._queue.clear()
                self._queued.clear()
            self._condition.notify_all()
        if mode == "automatic":
            self.enqueue_pending()

    def record(self, event: Mapping[str, Any]) -> None:
        pending = bool(self.url)
        self.store.add_event(event, pending=pending)
        if pending and self.mode == "automatic":
            self.enqueue(str(event["id"]))

    def enqueue(self, event_id: str, signature_mode: str = "valid") -> None:
        if signature_mode not in SIGNATURE_MODES:
            raise ValueError(f"Unsupported signature mode: {signature_mode}")
        key = f"{event_id}:{signature_mode}"
        with self._condition:
            if key not in self._queued:
                self._queue.append((event_id, signature_mode))
                self._queued.add(key)
            self._condition.notify_all()

    def enqueue_pending(self, *, newest_first: bool = False) -> None:
        events = [
            event
            for event in self.store.events()
            if event["delivery_state"] in {"pending", "failed"}
        ]
        if newest_first:
            events.reverse()
        for event in events:
            self.enqueue(event["id"])

    def deliver(
        self,
        event: Mapping[str, Any],
        *,
        signature_mode: str = "valid",
        retries: int = 1,
    ) -> bool:
        if not self.url:
            return False
        if signature_mode not in SIGNATURE_MODES:
            raise ValueError(f"Unsupported signature mode: {signature_mode}")
        with self._condition:
            if self._closed:
                return False
            self._active_deliveries += 1
        try:
            return self._deliver(event, signature_mode=signature_mode, retries=retries)
        finally:
            self._finish_delivery()

    def _deliver(
        self,
        event: Mapping[str, Any],
        *,
        signature_mode: str,
        retries: int,
    ) -> bool:
        payload = json.dumps(event, separators=(",", ":")).encode()
        timestamp = int(time.time())
        if signature_mode == "stale":
            timestamp -= 10 * 60
        signed = str(timestamp).encode() + b"." + payload
        digest = hmac.new(self.secret.encode(), signed, hashlib.sha256).hexdigest()
        if signature_mode == "invalid":
            digest = "0" * len(digest)
        signature = f"t={timestamp},v1={digest}"
        delivered = False
        self.store.set_event_state(str(event["id"]), "delivering")
        for attempt in range(retries):
            request = Request(
                self.url,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Stripe-Signature": signature,
                },
            )
            status: int | None = None
            error = ""
            try:
                with urlopen(request, timeout=2) as response:
                    status = response.status
                    delivered = 200 <= response.status < 300
            except HTTPError as exception:
                status = exception.code
                error = f"HTTP {exception.code}"
            except (URLError, TimeoutError) as exception:
                error = f"{type(exception).__name__}: {exception}"
            self.store.event_attempt(
                str(event["id"]),
                delivered,
                signature_mode=signature_mode,
                status=status,
                error=error,
            )
            with self._condition:
                closed = self._closed
            if delivered or closed:
                break
            if attempt + 1 < retries:
                time.sleep(0.05 * (attempt + 1))
        return delivered

    def wait_for_idle(self, timeout: float = 5) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._queue or self._active_deliveries:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._queue.clear()
            self._queued.clear()
            self._condition.notify_all()
        self._worker.join(timeout=3)
        self.wait_for_idle(timeout=3)

    def prepare_reset(self, timeout: float = 6) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            self._queue.clear()
            self._queued.clear()
            while self._active_deliveries:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def _work(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closed or (self._queue and self.mode == "automatic")
                )
                if self._closed:
                    return
                event_id, signature_mode = self._queue.popleft()
                self._queued.discard(f"{event_id}:{signature_mode}")
                self._active_deliveries += 1
            try:
                event = self.store.event(event_id)
                if event is not None:
                    self._deliver(event, signature_mode=signature_mode, retries=3)
            finally:
                self._finish_delivery()

    def _finish_delivery(self) -> None:
        with self._condition:
            self._active_deliveries -= 1
            self._condition.notify_all()
