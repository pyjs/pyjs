# Stripe Simulator Contract

The simulator is a deterministic development service, not a complete Stripe
implementation. It models the billing states that an application must handle
without making network calls to Stripe or charging a real payment method.

## Lifecycle

| Scenario | Invoice events | Subscription result | Entitlement intent |
| --- | --- | --- | --- |
| Checkout succeeds | `created`, `finalized`, `paid` | `active` | grant |
| Renewal succeeds | `created`, `finalized`, `paid` | `active` | retain |
| Soft decline | `created`, `finalized`, `payment_failed` | `past_due` | grace |
| Retry succeeds | `paid` | `active` | retain |
| Retries exhausted | repeated `payment_failed` | `unpaid` | revoke |
| Hard decline | `payment_failed` | `past_due` | grace |
| Authentication needed | `payment_action_required` | `past_due` | grace |
| Period-end cancellation | no new invoice | `canceled` | revoke |

A newly created invoice starts as `draft`, is finalized to `open`, and is then
paid or left open after a failed attempt. A retry operates on that same invoice
and increments its attempt count. Retryable failures schedule another attempt;
hard declines and authentication-required failures wait for operator or customer
action.

The default retry policy makes three payment attempts. Exhausting the policy
marks the invoice `uncollectible` and the subscription `unpaid`. Replacing a
payment method can retry an open invoice and recover the subscription.

## Webhook Delivery

Each state transition first records an immutable event. Delivery is separate
from billing state so tests can pause forwarding, deliver events later, send a
duplicate event ID, choose delivery order, or use an invalid or stale
signature. Every HTTP attempt is retained for inspection.

Automatic delivery is the default. Manual mode records new events without
forwarding them. Paused mode also stops queued automatic work until it is
resumed. Tests can wait for the delivery queue to become idle rather than rely
on arbitrary sleeps.

## Deliberate Limits

The contract does not cover Connect, tax, coupons, usage billing, proration,
refunds, disputes, multiple currencies, or real Stripe.js and PCI flows. Event
ordering is deterministic for reproducible tests; applications should still be
written to tolerate duplicate and out-of-order webhook delivery.
