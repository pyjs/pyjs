# PyJS Extras

`pyjs-extras` contains official, optional integrations between PyJS and
third-party services. Install only the provider dependencies you need:

```console
uv add "pyjs-extras[stripe]"
```

When the matching PyJS version is already a direct dependency, this convenience
spelling is equivalent:

```console
uv add "pyjs[stripe]"
```

## Stripe

The local simulator also supports explicit or clock-driven checkout expiry
and invoice retrieval/listing with customer, subscription and status filters.
Invoice lists support `limit` and forward `starting_after` pagination; reverse
pagination and other unsupported options (including expansion) are rejected.
Expired sessions cannot accept payment or complete
authentication. It remains a development simulator, not a Stripe replacement.

`pyjs_extras.stripe` provides five deliberately separate surfaces:

- `browser` contains typed Stripe.js declarations for transpiled code.
- `web` contains dependency-free SSR helpers for Stripe script and pricing
  table elements.
- `server` adapts the official Python Stripe SDK without depending on a web
  framework.
- `testing` provides an in-memory mock suitable for application tests.
- `simulator` runs a stateful local Stripe-compatible HTTP service for complete
  Checkout, webhook, subscription, and customer-portal scenarios.

Business concepts such as members, entitlements, and local subscription models
belong in an application or membership package rather than this integration.

Start the simulator with an application webhook destination:

```console
uv run pyjs-stripe-simulator \
    --webhook-url http://localhost:8000/stripe/webhook/
```

The API uses `sk_test_local`, webhooks use `whsec_local`, and state is stored in
`.pyjs-stripe.sqlite3` by default. Point `StripeGateway(api_base=...)` at
`http://127.0.0.1:12111` so application code follows the same SDK path used with
Stripe.

Open <http://127.0.0.1:12111> for the PyJS operator dashboard. It can select
successful, retryable-decline, hard-decline, or authentication-required
behavior for each subscription, run renewals, retry open invoices, advance the
clock, replace payment methods, and inspect invoice retry state. Webhook tools
can switch between automatic, manual, and paused forwarding; deliver pending
events oldest- or newest-first; send duplicate events; and inject invalid or
stale signatures. Test-only JSON state, reset, and clock controls remain
available under `/_test/`.

The simulator uses three payment attempts before marking a retryable invoice
uncollectible and its subscription unpaid. See
[`stripe/SIMULATOR.md`](stripe/SIMULATOR.md) for its lifecycle contract and
deliberate limits. Product, price, amount, currency, and maximum payment
attempts can be changed with command-line options; run
`pyjs-stripe-simulator --help` for the complete list.
