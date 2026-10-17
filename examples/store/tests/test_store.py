import asyncio
import builtins
import json

import pytest
from django.test import RequestFactory
from pyjs.javascript.transpiler import bundle_targets_with_source_maps
from pyjs.server import OperationError
from pyjs.web.domx import div
from pyjs.web.events import Event
from pyjs.web.ssr import render_html
from pyjs_examples.store import __main__ as store_main
from pyjs_examples.store import api as store_api
from pyjs_examples.store import models as db
from pyjs_examples.store import server as store_server
from pyjs_examples.store.api import (
    ApplicationAPI,
    account_summary,
    create_checkout,
    create_order,
    create_review,
    inventory_page,
    order_history_page,
    product_catalog,
    product_page,
    review_moderation_page,
    traffic_summary,
    update_inventory,
    visitor_event_snapshot,
    visitor_feed,
)
from pyjs_examples.store.core import (
    CheckoutDraft,
    InventoryChange,
    ReviewDraft,
    VisitorDraft,
)
from pyjs_examples.store.server import application
from pyjs_examples.store.store import (
    AccountDashboard,
    CatalogPage,
    InventoryPage,
    ReviewModerationPage,
    VisitorActivityPage,
    account_section,
    public_section,
    story_page,
)
from pyjs_extras.stripe.server import HostedSession


def test_store_entry_point_explains_its_optional_dependencies(monkeypatch):
    import_module = builtins.__import__

    def missing_django(name, *args, **kwargs):
        if name == "django":
            raise ModuleNotFoundError(name="django")
        return import_module(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_django)

    with pytest.raises(SystemExit) as caught:
        store_main.main()

    assert str(caught.value) == (
        "The Store example needs its optional server dependencies. "
        'Install them with: python -m pip install "pyjs-examples[store]"'
    )


def operation_pattern(name: str):
    return next(
        pattern
        for pattern in ApplicationAPI().urls
        if pattern.callback.__name__ == name
    )


def atomic_pattern():
    return next(
        pattern for pattern in ApplicationAPI().urls if pattern.callback.__name__ == "atomic"
    )


def call(pattern, payload):
    request = RequestFactory().post(
        "/api/" + str(pattern.pattern),
        data=json.dumps(payload),
        content_type="application/json",
    )
    return asyncio.run(pattern.callback(request))


def custom_element_class(source: str, class_name: str, tag_name: str) -> str:
    start = source.index(f"class {class_name} ")
    end = source.index(f"customElements.define('{tag_name}'", start)
    return source[start:end]


def test_store_bundle_hierarchy_matches_the_application_architecture():
    generated, stylesheet = bundle_targets_with_source_maps(
        application.bundle_targets()
    )
    root = generated["app"].javascript
    public = generated["app.public"].javascript
    catalog = generated["app.public.catalog"].javascript
    story = generated["app.public.story"].javascript
    account = generated["app.account"].javascript
    overview = generated["app.account.overview"].javascript
    inventory = generated["app.account.inventory"].javascript
    reviews = generated["app.account.reviews"].javascript
    visitors = generated["app.account.visitors"].javascript
    all_javascript = "\n".join(
        value.javascript for value in generated.values()
    )

    # Full custom-element bundles contain framework scaffolding; these targeted
    # assertions describe the placement contract without duplicating that output.
    assert "class StoreLayout extends NavigationLayout" in root
    assert "class AtomicBatch" in root
    assert "class StoreHeader extends Widget" in public
    assert "class CatalogPage extends Widget" in catalog
    assert "add_button.element.disabled = true;" in catalog
    assert "class AccountDashboard extends Widget" in overview
    assert "class StoreHeader extends Widget" not in catalog
    assert "class CatalogPage extends Widget" not in root
    assert "class AccountDashboard extends Widget" not in root
    assert "_hydrate()" in custom_element_class(
        catalog, "CatalogPage", "catalog-page"
    )
    assert "\n    _create(" not in custom_element_class(
        catalog, "CatalogPage", "catalog-page"
    )
    assert "_hydrate()" in custom_element_class(
        overview, "AccountDashboard", "account-dashboard"
    )
    assert "\n    _create(" not in custom_element_class(
        overview, "AccountDashboard", "account-dashboard"
    )
    assert "ApplicationAPI.prototype, 'products'" in catalog
    assert "ApplicationAPI.prototype, 'orders'" in catalog
    assert "ApplicationAPI.prototype, 'account'" not in catalog
    assert "ApplicationAPI.prototype, 'account'" in account
    assert "AccountResource.prototype, 'history'" in overview
    assert "AccountResource.prototype, 'inventory'" in inventory
    assert "class ReviewModerationPage extends Widget" in reviews
    assert "AccountResource.prototype, 'moderation'" in reviews
    assert "AccountResource.prototype, 'moderation'" not in inventory
    assert "class VisitorActivityPage extends Widget" in visitors
    assert "class Stream__VisitorEvent extends StreamSession" in visitors
    assert (
        "const {StreamSession} = "
        "__import_js__('pyjs.server.stream_client');"
    ) in visitors
    assert "var source = new EventSource(path);" in all_javascript
    assert (
        "const $path = this._path + '/events?arguments=' + "
        "encodeURIComponent(JSON.stringify($arguments));"
    ) in visitors
    assert "var session = api.account.visitors.events();" in visitors
    assert "session.resume_after(" in visitors
    assert "class StreamingList extends Widget" in visitors
    assert "class StreamingLog extends StreamingList" in visitors
    assert "AccountResource.prototype, 'visitors'" in visitors
    assert "AccountResource.prototype, 'visitors'" not in inventory
    assert "ApplicationAPI.prototype, 'products'" not in overview
    assert (
        "const api = new ApplicationAPI({transport: new DjangoFetchTransport()});"
        in all_javascript
    )
    assert "new $JSONAPIDecoder(JSON.parse(await this._request('summary', {}))" in (
        account
    )
    assert (
        'return this._decode_result($value, '
        '["model","pyjs.server.pagination.Page__Product"]);'
        in catalog
    )
    assert "async list(filters, page)" in catalog
    assert (
        "this._request('list', {filters: filters, page: page})"
    ) in catalog
    assert "product_ordering" not in all_javascript
    assert "product_queryset" not in all_javascript
    assert "recommended_products" not in all_javascript
    assert "DjangoRelationship" not in all_javascript
    assert "function hero_view()" not in all_javascript
    assert "function story_page()" not in all_javascript
    assert "class Theme" not in all_javascript
    assert story == (
        "import { define, importModule } from './app.public.js';\n"
        "export { define, importModule };\n"
    )
    assert ".max-w-3xl" in stylesheet


def test_store_server_render_contains_the_database_catalog():
    source = render_html(CatalogPage(product_page()))

    assert 'data-testid="store"' in source
    assert 'data-product-card="Canvas field bag"' in source
    assert 'data-product-card="Daily notebook"' in source
    assert 'data-product-card="Travel tumbler"' not in source
    assert 'data-resource-identity="[&quot;products&quot;,&quot;2&quot;]"' in source
    assert 'data-inventory="4"' in source
    assert 'data-slot="sheet-content"' in source
    assert (
        'data-direction="previous" disabled="" '
        'data-testid="catalog-previous"'
    ) in source
    assert 'data-direction="next" data-cursor=' in source
    assert 'data-testid="catalog-next"' in source


def test_store_sections_apply_distinct_scoped_themes():
    public = render_html(public_section(div("Catalog")))
    account = render_html(account_section(div("Orders")))

    assert 'data-pyjs-theme="northstar"' in public
    assert "--pyjs-primary:#78350f" in public
    assert 'data-pyjs-theme="northstar-account"' in account
    assert "--pyjs-primary:#fbbf24" in account


def test_store_static_assets_are_buffered_for_asgi(tmp_path, monkeypatch):
    asset = tmp_path / "store" / "app.js"
    asset.parent.mkdir()
    asset.write_text("const ready = true;", encoding="utf-8")
    monkeypatch.setattr(store_server, "STATIC_ROOT", tmp_path)

    response = store_server.static_asset(
        RequestFactory().get("/static/store/app.js"),
        "store/app.js",
    )

    assert response.streaming is False
    assert response.content == b"const ready = true;"
    assert response["Content-Type"] == "text/javascript"


def test_store_cart_state_and_checkout_boundary_work_in_python():
    store = CatalogPage(product_page())

    store.add_product(2, "Daily notebook", 2400)
    store.add_product(3, "Task lamp", 14800)

    assert store.cart_count == 2
    assert store.cart_total == 17200
    assert store.product_ids() == [2, 3]
    assert len(store.cart_items.children) == 2

    store.clear_cart(Event("click"))
    assert store.cart_count == 0
    assert store.cart_total == 0
    assert len(store.cart_items.children) == 1
    assert store.cart_items.children[0] is store.empty_cart


def test_account_history_and_inventory_render_from_typed_pages():
    create_order(
        CheckoutDraft(customer_name="Ada Lovelace", email="ada@example.com"),
        [1, 2],
    )
    history = order_history_page()

    account = render_html(AccountDashboard(account_summary(), history))
    inventory = render_html(InventoryPage(inventory_page()))

    assert "Order #1" in account
    assert "2 items" in account
    assert 'data-testid="order-history"' in account
    assert "Canvas field bag" in inventory
    assert 'data-testid="bulk-inventory-apply"' in inventory


def test_bulk_inventory_update_validates_before_mutating_any_product():
    updated = update_inventory(
        [
            InventoryChange(product_id=1, inventory=8),
            InventoryChange(product_id=3, inventory=8),
        ]
    )

    assert [product.inventory for product in updated] == [8, 8]
    assert db.Product.objects.get(pk=1).inventory == 8
    assert db.Product.objects.get(pk=3).inventory == 8

    with pytest.raises(OperationError, match="no longer exist"):
        update_inventory(
            [
                InventoryChange(product_id=1, inventory=2),
                InventoryChange(product_id=999, inventory=2),
            ]
        )

    assert db.Product.objects.get(pk=1).inventory == 8


def test_bulk_inventory_update_rejects_empty_and_duplicate_selections():
    with pytest.raises(OperationError, match="Select at least one"):
        update_inventory([])
    with pytest.raises(OperationError, match="only be updated once"):
        update_inventory(
            [
                InventoryChange(product_id=1, inventory=2),
                InventoryChange(product_id=1, inventory=3),
            ]
        )

    assert db.Product.objects.get(pk=1).inventory == 4


def test_checkout_reports_products_that_disappeared_from_the_cart():
    with pytest.raises(OperationError) as raised:
        create_order(
            CheckoutDraft(
                customer_name="Ada Lovelace",
                email="ada@example.com",
            ),
            [999],
        )

    assert raised.value.payload() == {
        "errors": [
            {
                "code": "unknown_product",
                "detail": "One or more products in the cart no longer exist.",
                "source": {"pointer": "/product_ids"},
                "status": "422",
                "title": "Validation error",
            }
        ]
    }


def test_atomic_endpoint_commits_typed_mutations_in_one_request():
    request = RequestFactory().post(
        "/api/atomic",
        data=json.dumps(
            {
                "operations": [
                    {
                        "operation": "account.inventory.set",
                        "arguments": {
                            "change": {"product_id": 1, "inventory": 7}
                        },
                    },
                    {
                        "operation": "account.inventory.set",
                        "arguments": {
                            "change": {"product_id": 2, "inventory": 7}
                        },
                    },
                ]
            }
        ),
        content_type="application/json",
    )

    response = asyncio.run(atomic_pattern().callback(request))
    results = json.loads(response.content)

    assert response.status_code == 200
    assert [result["data"]["attributes"]["inventory"] for result in results] == [
        7,
        7,
    ]
    assert list(
        db.Product.objects.filter(pk__in=(1, 2)).values_list(
            "inventory",
            flat=True,
        )
    ) == [7, 7]


def test_atomic_endpoint_rolls_back_and_points_to_the_failing_operation():
    request = RequestFactory().post(
        "/api/atomic",
        data=json.dumps(
            {
                "operations": [
                    {
                        "operation": "account.inventory.set",
                        "arguments": {
                            "change": {"product_id": 1, "inventory": 7}
                        },
                    },
                    {
                        "operation": "account.inventory.set",
                        "arguments": {
                            "change": {"product_id": 999, "inventory": 7}
                        },
                    },
                ]
            }
        ),
        content_type="application/json",
    )

    response = asyncio.run(atomic_pattern().callback(request))

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "unknown_product",
                "detail": "One or more selected products no longer exist.",
                "source": {
                    "pointer": "/operations/1/arguments/change",
                },
                "status": "422",
                "title": "Validation error",
            }
        ]
    }
    assert db.Product.objects.get(pk=1).inventory == 4


def test_product_resource_encodes_a_typed_cursor_page():
    pattern = operation_pattern("products_list")
    request = RequestFactory().post(
        "/api/products/list",
        data=json.dumps(
            {
                "filters": {
                    "available_only": False,
                    "search": "",
                    "sort": "featured",
                },
                "page": {"size": 2},
            }
        ),
        content_type="application/json",
    )

    response = asyncio.run(pattern.callback(request))
    document = json.loads(response.content)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert document["total"] == 4
    assert document["previous"] is None
    assert document["next"] is not None
    assert len(document["items"]) == 2
    assert document["items"][0] == {
        "cents": 8800,
        "description": "Waxed canvas with solid brass hardware.",
        "id": 1,
        "inventory": 4,
        "name": "Canvas field bag",
        "slug": "canvas-field-bag",
        "symbol": "▰",
        "tone": "clay",
    }


def test_visitor_activity_uses_a_typed_cursor_feed_and_data_chart():
    snapshot = visitor_event_snapshot()
    first = snapshot.value
    summary = traffic_summary()
    activity = VisitorActivityPage(summary, snapshot)
    source = render_html(activity)

    assert summary.total == 12
    assert summary.labels == [
        "Aug 14",
        "Aug 15",
        "Aug 16",
        "Aug 17",
        "Aug 18",
        "Aug 19",
        "Aug 20",
    ]
    assert summary.values == [2, 1, 2, 1, 2, 2, 2]
    assert [visit.id for visit in first.items] == [12, 11, 10, 9]
    assert first.next is not None
    assert f'data-stream-sequence="{snapshot.sequence}"' in source
    assert source.count('data-visitor-event="') == 4
    assert source.count('data-slot="streaming-log-line"') == 4
    assert source.count('data-slot="chart-point"') == 7
    assert "Load older visits" in source

    activity.receive_visit(first.items[0])
    deduplicated = render_html(activity)

    assert deduplicated.count('data-visitor-event="') == 4
    assert deduplicated.count('data-slot="streaming-log-line"') == 4

    response = call(
        operation_pattern("account_visitors_list"),
        {"page": {"after": first.next, "size": 4}},
    )
    document = json.loads(response.content)

    assert response.status_code == 200
    assert [visit["id"] for visit in document["items"]] == [8, 7, 6, 5]
    assert document["next"] is not None


def test_recording_a_visitor_persists_and_publishes_the_typed_event():
    subscription = visitor_feed.backend.subscribe(visitor_feed.scope)
    try:
        response = call(
            operation_pattern("account_visitors_record"),
            {
                "draft": VisitorDraft(
                    path="/products/task-lamp/",
                    source="Live test",
                    region="Chicago, US",
                    device="Mobile",
                ).model_dump()
            },
        )
        document = json.loads(response.content)
        published = subscription.receive_nowait()
    finally:
        subscription.close()

    assert response.status_code == 200
    assert document["data"]["id"] == "13"
    assert document["data"]["attributes"]["path"] == (
        "/products/task-lamp/"
    )
    assert published.scope == "visitors"
    assert published.value.id == 13
    assert published.value.source == "Live test"


def test_product_detail_includes_bounded_reviews_and_recommendations():
    response = call(
        operation_pattern("products_get"),
        {"product_id": 1},
    )

    assert response.status_code == 200
    assert json.loads(response.content) == {
        "data": {
            "type": "products",
            "id": "1",
            "attributes": {
                "slug": "canvas-field-bag",
                "name": "Canvas field bag",
                "description": "Waxed canvas with solid brass hardware.",
                "cents": 8800,
                "symbol": "▰",
                "tone": "clay",
                "inventory": 4,
            },
            "relationships": {
                "reviews": {
                    "data": [
                        {"type": "reviews", "id": "4"},
                        {"type": "reviews", "id": "3"},
                        {"type": "reviews", "id": "2"},
                    ]
                },
                "recommendations": {
                    "data": [
                        {"type": "recommendations", "id": "3"},
                        {"type": "recommendations", "id": "2"},
                    ]
                },
            },
        },
        "included": [
            {
                "type": "reviews",
                "id": "4",
                "attributes": {
                    "author_name": "Noah",
                    "rating": 3,
                    "body": "Well made, though a little larger than I expected.",
                },
            },
            {
                "type": "reviews",
                "id": "3",
                "attributes": {
                    "author_name": "Inez",
                    "rating": 5,
                    "body": "Comfortable on a long walk and easy to organize.",
                },
            },
            {
                "type": "reviews",
                "id": "2",
                "attributes": {
                    "author_name": "Theo",
                    "rating": 4,
                    "body": (
                        "A sturdy daily bag with just the right number of pockets."
                    ),
                },
            },
            {
                "type": "recommendations",
                "id": "3",
                "attributes": {
                    "slug": "task-lamp",
                    "name": "Task lamp",
                    "description": "Warm, dimmable light in powder-coated steel.",
                    "cents": 14800,
                    "symbol": "◒",
                    "tone": "ink",
                    "inventory": 3,
                },
            },
            {
                "type": "recommendations",
                "id": "2",
                "attributes": {
                    "slug": "daily-notebook",
                    "name": "Daily notebook",
                    "description": "Lay-flat binding and 192 fountain-pen pages.",
                    "cents": 2400,
                    "symbol": "▤",
                    "tone": "moss",
                    "inventory": 12,
                },
            },
        ],
    }


def test_product_reviews_are_publicly_paginated_and_exclude_pending_reviews():
    pending = create_review(
        1,
        ReviewDraft(
            author_name="Ada",
            rating=5,
            body="Exactly the field bag I was looking for.",
        ),
    )

    response = call(
        operation_pattern("products_reviews_list"),
        {"product_id": 1, "page": {"size": 2}},
    )
    document = json.loads(response.content)

    assert response.status_code == 200
    assert document["previous"] is None
    assert document["next"] is not None
    assert document["total"] == 4
    assert [review["author_name"] for review in document["items"]] == [
        "Noah",
        "Inez",
    ]
    assert pending.id not in [review["id"] for review in document["items"]]


def test_review_submission_and_moderation_use_typed_resource_operations():
    response = call(
        operation_pattern("products_reviews_submit"),
        {
            "product_id": 1,
            "draft": {
                "author_name": "  Ada  ",
                "rating": 5,
                "body": "  Exactly the field bag I wanted.  ",
            },
        },
    )

    assert response.status_code == 200
    assert json.loads(response.content) == {
        "data": {
            "type": "reviews",
            "id": "7",
            "attributes": {
                "author_name": "Ada",
                "rating": 5,
                "body": "Exactly the field bag I wanted.",
            },
        }
    }
    review = db.Review.objects.get(pk=7)
    assert review.status == db.Review.Status.PENDING

    moderation = call(
        operation_pattern("account_moderation_set_status"),
        {"review_id": review.id, "status": "published"},
    )

    assert moderation.status_code == 200
    assert json.loads(moderation.content) == {
        "data": {
            "type": "moderation",
            "id": "7",
            "attributes": {
                "product_id": 1,
                "author_name": "Ada",
                "rating": 5,
                "body": "Exactly the field bag I wanted.",
                "status": "published",
                "product_name": "Canvas field bag",
            },
        }
    }
    review.refresh_from_db()
    assert review.status == db.Review.Status.PUBLISHED


def test_review_submission_reports_validation_at_the_owning_fields():
    response = call(
        operation_pattern("products_reviews_submit"),
        {
            "product_id": 1,
            "draft": {
                "author_name": "  ",
                "rating": 5,
                "body": "A useful review.",
            },
        },
    )

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "short_author_name",
                "detail": "Enter at least two non-space characters.",
                "source": {"pointer": "/draft/author_name"},
                "status": "422",
                "title": "Validation error",
            }
        ]
    }
    assert db.Review.objects.count() == 6


def test_review_moderation_page_uses_real_django_models_and_properties():
    create_review(
        2,
        ReviewDraft(
            author_name="Ada",
            rating=4,
            body="Excellent paper and binding.",
        ),
    )

    page = review_moderation_page()
    source = render_html(ReviewModerationPage(page))

    assert page.total == 7
    assert page.items[0].product_name == "Daily notebook"
    assert page.items[0].status == "pending"
    assert "Review moderation" in source
    assert "Excellent paper and binding." in source


def test_product_resource_rejects_a_tampered_cursor_as_client_input():
    response = call(
        operation_pattern("products_list"),
        {
            "filters": {
                "available_only": False,
                "search": "",
                "sort": "featured",
            },
            "page": {"after": "not-a-signed-cursor", "size": 2},
        },
    )

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "invalid_cursor",
                "detail": "Invalid pagination cursor.",
                "status": "422",
                "title": "Validation error",
            }
        ]
    }


def test_product_resource_filters_using_a_typed_query_argument():
    pattern = operation_pattern("products_list")
    request = RequestFactory().post(
        "/api/products/list",
        data=json.dumps(
            {
                "filters": {
                    "available_only": False,
                    "search": "lamp",
                    "sort": "featured",
                },
                "page": {"size": 2},
            }
        ),
        content_type="application/json",
    )

    response = asyncio.run(pattern.callback(request))
    document = json.loads(response.content)

    assert response.status_code == 200
    assert [product["name"] for product in document["items"]] == ["Task lamp"]
    assert document["total"] == 1


def test_product_resource_sorts_and_filters_one_typed_query():
    request = RequestFactory().post(
        "/api/products/list",
        data=json.dumps(
            {
                "filters": {
                    "available_only": True,
                    "search": "",
                    "sort": "price-descending",
                },
                "page": {"size": 10},
            }
        ),
        content_type="application/json",
    )

    response = asyncio.run(operation_pattern("products_list").callback(request))
    document = json.loads(response.content)

    assert response.status_code == 200
    assert document["total"] == 3
    assert [product["name"] for product in document["items"]] == [
        "Task lamp",
        "Canvas field bag",
        "Daily notebook",
    ]


def test_product_resource_rejects_an_unknown_sort_value():
    request = RequestFactory().post(
        "/api/products/list",
        data=json.dumps(
            {
                "filters": {
                    "available_only": False,
                    "search": "",
                    "sort": "surprise-me",
                },
                "page": {"size": 2},
            }
        ),
        content_type="application/json",
    )

    response = asyncio.run(operation_pattern("products_list").callback(request))

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "literal_error",
                "detail": (
                    "Input should be 'featured', 'name', 'price-ascending' or "
                    "'price-descending'"
                ),
                "source": {"pointer": "/filters/sort"},
                "status": "422",
                "title": "Validation error",
            }
        ]
    }


def test_checkout_uses_normal_orm_models_and_updates_inventory_atomically():
    receipt = create_order(
        CheckoutDraft(customer_name="Ada Lovelace", email="ada@example.com"),
        [2, 2, 3],
    )

    assert receipt.model_dump() == {
        "customer_name": "Ada Lovelace",
        "email": "ada@example.com",
        "id": 1,
        "items": [
            {
                "product": product_catalog()[1].model_dump(),
                "quantity": 2,
                "unit_cents": 2400,
            },
            {
                "product": product_catalog()[2].model_dump(),
                "quantity": 1,
                "unit_cents": 14800,
            },
        ],
        "status": "ready",
        "total_cents": 19600,
    }
    assert db.Product.objects.get(pk=2).inventory == 10
    assert db.Product.objects.get(pk=3).inventory == 2
    assert db.Order.objects.get(pk=receipt.id).items.count() == 2
    assert account_summary().model_dump() == {
        "id": 1,
        "order_count": 1,
        "total_cents": 19600,
    }


def test_checkout_creates_a_local_hosted_payment_session():
    result = create_checkout(
        CheckoutDraft(customer_name="Ada Lovelace", email="ada@example.com"),
        [1, 2],
        "https://store.test/",
        "checkout-local-session",
    )

    assert result.receipt.total_cents == 11200
    assert result.checkout_url.startswith(
        "https://store.test/stripe/mock/checkout/cs_mock_"
    )


def test_checkout_commits_the_order_before_payment_and_retries_safely(
    monkeypatch,
):
    requests = []

    class FlakyGateway:
        def create_payment(self, request):
            requests.append(request)
            if len(requests) == 1:
                raise RuntimeError("payment provider unavailable")
            return HostedSession(
                "cs_retry",
                "checkout",
                "https://store.test/checkout/cs_retry",
            )

    gateway = FlakyGateway()
    monkeypatch.setattr(store_api, "payment_gateway", lambda base_url: gateway)
    draft = CheckoutDraft(
        customer_name="Ada Lovelace",
        email="ada@example.com",
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        create_checkout(
            draft,
            [1],
            "https://store.test/",
            "checkout-retry",
        )

    order = db.Order.objects.get()
    assert order.checkout_key == "checkout-retry"
    assert db.Product.objects.get(pk=1).inventory == 3

    result = create_checkout(
        draft,
        [1],
        "https://store.test/",
        "checkout-retry",
    )

    assert result.receipt.id == order.id
    assert result.checkout_url == "https://store.test/checkout/cs_retry"
    assert db.Order.objects.count() == 1
    assert db.Product.objects.get(pk=1).inventory == 3
    assert [request.idempotency_key for request in requests] == [
        "checkout-retry",
        "checkout-retry",
    ]

    with pytest.raises(OperationError) as raised:
        create_checkout(
            draft,
            [2],
            "https://store.test/",
            "checkout-retry",
        )

    assert raised.value.payload() == {
        "errors": [
            {
                "code": "checkout_conflict",
                "detail": "The checkout identifier belongs to another order.",
                "source": {"pointer": "/checkout_key"},
                "status": "409",
                "title": "Checkout conflict",
            }
        ]
    }


def test_story_is_a_static_server_rendered_page():
    source = render_html(story_page())

    assert "Useful things, considered carefully." in source
    assert "ships no page-specific JavaScript" in source


def test_checkout_rejects_empty_and_overstocked_orders_without_partial_writes():
    draft = CheckoutDraft(customer_name="Ada Lovelace", email="ada@example.com")

    with pytest.raises(OperationError, match="Add at least one product"):
        create_order(draft, [])
    with pytest.raises(OperationError, match="no longer available"):
        create_order(draft, [3, 3, 3, 3])

    assert db.Order.objects.count() == 0
    assert db.Product.objects.get(pk=3).inventory == 3


def test_checkout_reports_server_business_rules_at_the_owning_form_field():
    draft = CheckoutDraft(customer_name="  ", email="ada@example.com")

    with pytest.raises(OperationError) as caught:
        create_order(draft, [1])

    assert caught.value.issues[0].detail == "Enter at least two non-space characters."
    assert caught.value.issues[0].location == ["draft", "customer_name"]
    assert caught.value.issues[0].code == "short_customer_name"
    assert db.Order.objects.count() == 0


def test_checkout_transports_structured_field_errors():
    request = RequestFactory().post(
        "/api/orders/checkout",
        data=json.dumps(
            {
                "draft": {
                    "customer_name": "  ",
                    "email": "ada@example.com",
                },
                "product_ids": [1],
                "checkout_key": "checkout-field-error",
            }
        ),
        content_type="application/json",
    )

    response = asyncio.run(operation_pattern("orders_checkout").callback(request))

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "short_customer_name",
                "detail": "Enter at least two non-space characters.",
                "source": {"pointer": "/draft/customer_name"},
                "status": "422",
                "title": "Validation error",
            }
        ]
    }
    assert db.Order.objects.count() == 0
