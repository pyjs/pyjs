# Store Example

Northstar Supply is PyJS's business application and Django integration example.
It demonstrates:

- a responsive, server-rendered product storefront;
- normal Django models, disposable SQLite schema, and fixture data;
- shared Pydantic models and generated typed client API resources;
- typed catalog search, sorting, availability filters, and signed cursor pages;
- bounded recent-review includes and batched product recommendations;
- public review pagination, validated submission, and seller moderation;
- typed, cursor-paginated account order history;
- an infinite visitor activity feed and data-driven SVG traffic chart;
- a model-driven checkout form and structured operation errors;
- seller inventory selection with one validated, atomic bulk update;
- DOM-owned shopping-bag state;
- CSRF-protected mutations and transactional inventory updates;
- SSE-backed live catalog updates across browser windows;
- accessible stock components, browser tests, and visual tests;
- scoped public and account themes configured with semantic design tokens;
- automatic application, public-section, account-section, and page bundles;
- server-only render helpers and hydration-only interactive page elements; and
- a local hosted-payment flow backed by `pyjs_extras.stripe`.

Store is the main themability example. Its public and account sections use
different `Theme` values while reusing the same stock components. Theme tokens
are scoped to their provider, so embedded applications and nested sections do
not need global CSS configuration.

## Architecture

Store is the high-level counterpart to Chat's raw WebSocket protocol:

- `models.py` owns the authoritative Django database models;
- `core.py` defines Pydantic values shared with the browser;
- `api.py` defines typed resource queries and mutations whose bodies remain
  on the server and become generated client proxies;
- `store.py` renders the initial page on the server, owns transient cart state
  in the DOM, and maps operation errors back to model-form fields; and
- `server.py` and `urls.py` provide the narrow Django integration boundary.

The first catalog page is present in the initial server-rendered HTML. One
`CatalogFilters` model carries search, sorting, and availability state, while a
separate typed page request carries its opaque, query-bound cursor. Changing a
filter resets the cursor, while `LiveSession` refreshes the exact active query
through one SSE connection. Checkout validates the shared draft, executes a
transactional order and inventory mutation, and publishes the committed
inventory change to other open windows. The external payment request begins
only after that transaction commits. A client-stable checkout key lets a retry
reuse the order and provider session without decrementing inventory twice.

Product details demonstrate both Django relationship-loader modes. Recent
reviews use one ordered prefetch limited independently for each product.
Recommendations use one batched computed loader and share the same JSON:API
document, identity map, and typed client access as ordinary relationships.
The public review resource continues beyond the bounded include with signed
cursor pages. New reviews are validated into a pending state, remain absent
from public reads, and appear after a seller publishes them from the account
moderation page.

The account area presents typed order history and a separate seller inventory
page. Inventory changes validate the complete selection before changing any
row. The example shows both a specialized `bulk_update()` operation and an
`api.atomic()` batch assembled from typed per-product mutations. Both publish a
single live invalidation after commit.

The visitor activity page keeps keyset pagination on the server while an
`InfiniteScroll` control appends each older page to the existing DOM. Its
explicit button remains available to keyboard and assistive-technology users;
an `IntersectionObserver` sentinel provides automatic loading. The same page
feeds aggregated daily values into a dependency-free SVG `LineChart`.

Checkout creates a one-time hosted payment through the same stable Stripe
gateway used with the official SDK. During development, Store supplies the
stateful mock gateway from `pyjs_extras.stripe`, so the browser follows a real
redirect and completion flow without network access or a real card. The real
and mock gateways both honor the checkout key as a payment idempotency key.

The application also demonstrates PyJS's static bundle hierarchy:

```text
app.js
    app.public.js
        app.public.catalog.js
        app.public.story.js
    app.account.js
        app.account.overview.js
        app.account.inventory.js
        app.account.reviews.js
        app.account.visitors.js
```

`StoreHeader` is shared by public pages. Catalog behavior and the product and
order API branches stay in the catalog bundle; account behavior and its API
branch stay in the account page bundle. The story is rendered on the server,
contributes its Tailwind classes to the shared stylesheet, and has no
page-specific JavaScript definitions. `CatalogPage` and `AccountDashboard`
ship hydration code, but their server-only `_create()` paths are omitted.

Direct requests reference the leaf bundle. Progressive navigation returns the
server-rendered page plus that bundle URL, imports it, and then installs and
hydrates the new DOM without reloading the application shell.

## Run the store

For an installed release, add Store's server dependencies:

```bash
python -m pip install "pyjs-examples[store]"
```

From the repository root:

```bash
uv run python -m pyjs_examples.store
```

The development database is rebuilt from `fixtures/store.json` each time the
server starts. Store intentionally ships without migration history because it
is a disposable example rather than a long-lived application. Its runner uses
`migrate --run-syncdb`; generate a fresh initial migration after adapting the
models into your own Django project.

## Run the tests

```bash
uv run pytest -q examples/store/tests
```

Run the visual scenario with:

```bash
uv run python examples/store/visual_test.py
```
