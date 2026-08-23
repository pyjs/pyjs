from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from pyjs import js
from pyjs.server import (
    API,
    CursorPageRequest,
    Page,
    Relationship,
    Resource,
    include_paths,
    mutation,
    operation_error,
    query,
)
from pyjs.server.django import (
    DjangoFetchTransport,
    dispatch_sync,
    queryset_page,
    queryset_result,
    relationship,
)
from pyjs_extras.stripe.server import PaymentRequest
from pyjs_extras.stripe.testing import MockStripeGateway

from . import models as db
from .core import (
    AccountSummary,
    CatalogFilters,
    CheckoutDraft,
    CheckoutResult,
    InventoryChange,
    ModeratedReview,
    OrderLine,
    OrderReceipt,
    OrderSummary,
    Product,
    ProductSort,
    Review,
    ReviewDraft,
    ReviewStatus,
    TrafficSummary,
    VisitorEvent,
)

PAYMENT_STATE: dict[str, object] = {}


def payment_gateway(base_url: str) -> MockStripeGateway:
    return MockStripeGateway(PAYMENT_STATE, base_url)


def product_queryset(
    filters: CatalogFilters,
):
    products = db.Product.objects.all()
    search = filters.search.strip()
    if search:
        products = products.filter(name__icontains=search)
    if filters.available_only:
        products = products.filter(inventory__gt=0)
    return products.order_by(*product_ordering(filters.sort))


def product_ordering(sort: ProductSort) -> tuple[str, ...]:
    if sort == "name":
        return ("name", "id")
    if sort == "price-ascending":
        return ("cents", "id")
    if sort == "price-descending":
        return ("-cents", "-id")
    return ("id",)


def product_catalog(
    filters: CatalogFilters | None = None,
) -> list[Product]:
    if filters is None:
        filters = CatalogFilters()
    return [
        Product.model_validate(product, from_attributes=True)
        for product in product_queryset(filters)
    ]


def product_page(
    filters: CatalogFilters | None = None,
    page: CursorPageRequest | None = None,
) -> Page[Product]:
    if filters is None:
        filters = CatalogFilters()
    if page is None:
        page = CursorPageRequest(size=2)
    return dispatch_sync(
        api.products.list,
        filters,
        page,
    )


def inventory_page(
    page: CursorPageRequest | None = None,
) -> Page[Product]:
    if page is None:
        page = CursorPageRequest(size=10)
    return dispatch_sync(
        api.account.inventory.list,
        page,
    )


def order_receipt(order: db.Order) -> OrderReceipt:
    lines = order.items.select_related("product").order_by("id")
    return OrderReceipt(
        id=order.id,
        customer_name=order.customer_name,
        email=order.email,
        total_cents=order.total_cents,
        status=order.status,
        items=[
            OrderLine(
                product=Product.model_validate(line.product, from_attributes=True),
                quantity=line.quantity,
                unit_cents=line.unit_cents,
            )
            for line in lines
        ],
    )


def account_summary() -> AccountSummary:
    orders = db.Order.objects.all()
    return AccountSummary(
        id=1,
        order_count=orders.count(),
        total_cents=sum(order.total_cents for order in orders),
    )


def order_history_page(
    page: CursorPageRequest | None = None,
) -> Page[OrderSummary]:
    if page is None:
        page = CursorPageRequest(size=5)
    return dispatch_sync(
        api.account.history.list,
        page,
    )


def review_moderation_page(
    page: CursorPageRequest | None = None,
) -> Page[ModeratedReview]:
    if page is None:
        page = CursorPageRequest(size=10)
    return dispatch_sync(api.account.moderation.list, page)


def visitor_event_page(
    page: CursorPageRequest | None = None,
) -> Page[VisitorEvent]:
    if page is None:
        page = CursorPageRequest(size=4)
    return dispatch_sync(api.account.visitors.list, page)


def traffic_summary() -> TrafficSummary:
    return dispatch_sync(api.account.visitors.summary)


@transaction.atomic
def update_inventory(
    changes: list[InventoryChange],
    argument: str = "changes",
) -> list[Product]:
    if not changes:
        raise operation_error(
            "Select at least one product.",
            argument,
            code="empty_selection",
        )
    product_ids = [change.product_id for change in changes]
    if len(product_ids) != len(set(product_ids)):
        raise operation_error(
            "Each product can only be updated once.",
            argument,
            code="duplicate_product",
        )
    products = {
        product.id: product
        for product in db.Product.objects.select_for_update().filter(
            id__in=product_ids
        )
    }
    if len(products) != len(product_ids):
        raise operation_error(
            "One or more selected products no longer exist.",
            argument,
            code="unknown_product",
        )
    for change in changes:
        products[change.product_id].inventory = change.inventory
    db.Product.objects.bulk_update(products.values(), ("inventory",))
    return [
        Product.model_validate(products[product_id], from_attributes=True)
        for product_id in product_ids
    ]


@transaction.atomic
def create_order(
    draft: CheckoutDraft,
    product_ids: list[int],
    checkout_key: str | None = None,
) -> OrderReceipt:
    customer_name = draft.customer_name.strip()
    if len(customer_name) < 2:
        raise operation_error(
            "Enter at least two non-space characters.",
            "draft",
            "customer_name",
            code="short_customer_name",
        )
    if not product_ids:
        raise operation_error(
            "Add at least one product before checking out.",
            "product_ids",
            code="empty_cart",
        )
    quantities = {
        product_id: product_ids.count(product_id) for product_id in set(product_ids)
    }
    if checkout_key is not None:
        checkout_key = checkout_key.strip()
        if not checkout_key or len(checkout_key) > 64:
            raise operation_error(
                "The checkout identifier is invalid.",
                "checkout_key",
                code="invalid_checkout_key",
            )
        existing = db.Order.objects.filter(checkout_key=checkout_key).first()
        if existing is not None:
            existing_quantities = {
                product_id: quantity
                for product_id, quantity in existing.items.values_list(
                    "product_id",
                    "quantity",
                )
            }
            if (
                existing.customer_name != customer_name
                or existing.email != str(draft.email)
                or existing_quantities != quantities
            ):
                raise operation_error(
                    "The checkout identifier belongs to another order.",
                    "checkout_key",
                    status=409,
                    title="Checkout conflict",
                    code="checkout_conflict",
                )
            return order_receipt(existing)
    products = {
        product.id: product
        for product in db.Product.objects.select_for_update().filter(
            id__in=set(product_ids)
        )
    }
    if len(products) != len(set(product_ids)):
        raise operation_error(
            "One or more products in the cart no longer exist.",
            "product_ids",
            code="unknown_product",
        )
    for product_id, quantity in quantities.items():
        if products[product_id].inventory < quantity:
            raise operation_error(
                products[product_id].name + " is no longer available in that quantity.",
                "product_ids",
                code="insufficient_inventory",
            )
    total = sum(
        products[product_id].cents * quantity
        for product_id, quantity in quantities.items()
    )
    order = db.Order.objects.create(
        checkout_key=checkout_key,
        customer_name=customer_name,
        email=str(draft.email),
        total_cents=total,
    )
    for product_id, quantity in quantities.items():
        product = products[product_id]
        db.OrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            unit_cents=product.cents,
        )
        product.inventory -= quantity
        product.save(update_fields=("inventory",))
    return order_receipt(order)


def create_checkout(
    draft: CheckoutDraft,
    product_ids: list[int],
    base_url: str,
    checkout_key: str,
) -> CheckoutResult:
    receipt = create_order(draft, product_ids, checkout_key)
    payment = payment_gateway(base_url).create_payment(
        PaymentRequest(
            receipt.total_cents,
            "Northstar order #" + str(receipt.id),
            base_url + "account/",
            base_url,
            client_reference_id=str(receipt.id),
            customer_email=receipt.email,
            idempotency_key=checkout_key,
            metadata={"order_id": str(receipt.id)},
        )
    )
    return CheckoutResult(receipt=receipt, checkout_url=payment.url)


def recommended_products(products):
    candidates = list(db.Product.objects.filter(inventory__gt=0))
    recommendations = {}
    for product in products:
        available = [
            candidate for candidate in candidates if candidate.pk != product.pk
        ]
        available.sort(
            key=lambda candidate: (
                candidate.tone != product.tone,
                abs(candidate.cents - product.cents),
                candidate.pk,
            )
        )
        recommendations[product.pk] = available
    return recommendations


def create_review(product_id: int, draft: ReviewDraft) -> Review:
    if not db.Product.objects.filter(pk=product_id).exists():
        raise operation_error(
            "This product is no longer available.",
            "product_id",
            code="unknown_product",
        )
    author_name = draft.author_name.strip()
    body = draft.body.strip()
    if len(author_name) < 2:
        raise operation_error(
            "Enter at least two non-space characters.",
            "draft",
            "author_name",
            code="short_author_name",
        )
    if len(body) < 4:
        raise operation_error(
            "Enter at least four non-space characters.",
            "draft",
            "body",
            code="short_review",
        )
    review = db.Review.objects.create(
        product_id=product_id,
        author_name=author_name,
        rating=draft.rating,
        body=body,
        created_at=timezone.now(),
    )
    return Review.model_validate(review, from_attributes=True)


def moderate_review(review_id: int, status: ReviewStatus) -> ModeratedReview:
    try:
        review = db.Review.objects.select_related("product").get(pk=review_id)
    except db.Review.DoesNotExist:
        raise operation_error(
            "This review no longer exists.",
            "review_id",
            code="unknown_review",
        ) from None
    review.status = status
    review.save(update_fields=("status",))
    return ModeratedReview.model_validate(review, from_attributes=True)


@js
class ReviewResource(Resource[Review]):
    @query
    async def list(
        self,
        product_id: int,
        page: CursorPageRequest,
    ) -> Page[Review]:
        return queryset_page(
            db.Review.objects.filter(
                product_id=product_id,
                status=db.Review.Status.PUBLISHED,
            ),
            page,
            order_by=("-created_at", "-id"),
            include_total=True,
        )

    @mutation
    async def submit(self, product_id: int, draft: ReviewDraft) -> Review:
        return await sync_to_async(create_review)(product_id, draft)


@js
class RecommendationResource(Resource[Product]):
    pass


@js
class ProductResource(Resource[Product]):
    reviews: Relationship[list[Review], ReviewResource] = relationship(
        queryset=db.Review.objects.filter(
            status=db.Review.Status.PUBLISHED,
        ).order_by("-created_at", "-id"),
        limit=3,
    )
    recommendations: Relationship[
        list[Product], RecommendationResource
    ] = relationship(
        load=recommended_products,
        limit=2,
    )

    @query
    async def list(
        self,
        filters: CatalogFilters,
        page: CursorPageRequest,
    ) -> Page[Product]:
        return queryset_page(
            product_queryset(filters),
            page,
            order_by=product_ordering(filters.sort),
            include_total=True,
        )

    @query
    async def get(self, product_id: int) -> Product | None:
        return queryset_result(
            db.Product.objects.filter(pk=product_id),
            include_paths=include_paths(
                self,
                self.reviews,
                self.recommendations,
            ),
        )


@js
class OrderResource(Resource[OrderReceipt]):
    @mutation
    async def checkout(
        self,
        draft: CheckoutDraft,
        product_ids: list[int],
        checkout_key: str,
    ) -> CheckoutResult:
        base_url = self.request.build_absolute_uri("/")
        return await sync_to_async(create_checkout)(
            draft,
            product_ids,
            base_url,
            checkout_key,
        )


@js
class OrderHistoryResource(Resource[OrderSummary]):
    @query
    async def list(self, page: CursorPageRequest) -> Page[OrderSummary]:
        return queryset_page(
            db.Order.objects.prefetch_related("items"),
            page,
            order_by=("-created_at", "-id"),
            include_total=True,
        )


@js
class InventoryResource(Resource[Product]):
    @mutation
    async def set(self, change: InventoryChange) -> Product:
        return (await sync_to_async(update_inventory)([change], "change"))[0]

    @mutation
    async def update(
        self,
        changes: list[InventoryChange],
    ) -> list[Product]:
        return await sync_to_async(update_inventory)(changes)

    @query
    async def list(self, page: CursorPageRequest) -> Page[Product]:
        return queryset_page(
            db.Product.objects.all(),
            page,
            order_by=("name", "id"),
            include_total=True,
        )


@js
class ReviewModerationResource(Resource[ModeratedReview]):
    @query
    async def list(self, page: CursorPageRequest) -> Page[ModeratedReview]:
        return queryset_page(
            db.Review.objects.select_related("product"),
            page,
            order_by=("-created_at", "-id"),
            include_total=True,
        )

    @mutation
    async def set_status(
        self,
        review_id: int,
        status: ReviewStatus,
    ) -> ModeratedReview:
        return await sync_to_async(moderate_review)(review_id, status)


def visitor_summary() -> TrafficSummary:
    daily = list(
        db.VisitorEvent.objects.annotate(day=TruncDate("occurred_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    return TrafficSummary(
        total=db.VisitorEvent.objects.count(),
        labels=[row["day"].strftime("%b %d") for row in daily],
        values=[row["total"] for row in daily],
    )


@js
class VisitorResource(Resource[VisitorEvent]):
    @query
    async def list(self, page: CursorPageRequest) -> Page[VisitorEvent]:
        return queryset_page(
            db.VisitorEvent.objects.all(),
            page,
            order_by=("-occurred_at", "-id"),
            include_total=True,
        )

    @query
    async def summary(self) -> TrafficSummary:
        return await sync_to_async(visitor_summary)()


@js
class AccountResource(Resource[AccountSummary]):
    history: OrderHistoryResource
    inventory: InventoryResource
    moderation: ReviewModerationResource
    visitors: VisitorResource

    @query
    async def summary(self) -> AccountSummary:
        return await sync_to_async(account_summary)()


@js
class ApplicationAPI(API):
    products: ProductResource
    orders: OrderResource
    account: AccountResource


api = ApplicationAPI(transport=DjangoFetchTransport())
