from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from pyjs import js
from pyjs.server.django import ModelSchema

from . import models as db

type ProductSort = Literal[
    "featured",
    "name",
    "price-ascending",
    "price-descending",
]
type ReviewStatus = Literal["pending", "published", "rejected"]


@js
class CatalogFilters(BaseModel):
    search: str = ""
    sort: ProductSort = "featured"
    available_only: bool = False


@js
class Product(ModelSchema):
    id: int

    class Meta:
        model = db.Product
        fields = (
            "slug",
            "name",
            "description",
            "cents",
            "symbol",
            "tone",
            "inventory",
        )


@js
class Review(ModelSchema):
    id: int

    class Meta:
        model = db.Review
        fields = ("author_name", "rating", "body")


@js
class ReviewDraft(BaseModel):
    author_name: str = Field("", min_length=2, max_length=80)
    rating: int = Field(5, ge=1, le=5)
    body: str = Field("", min_length=4, max_length=320)


@js
class ModeratedReview(ModelSchema):
    id: int
    product_name: str

    class Meta:
        model = db.Review
        fields = ("product_id", "author_name", "rating", "body", "status")


@js
class CheckoutDraft(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)


@js
class OrderLine(BaseModel):
    product: Product
    quantity: int
    unit_cents: int


@js
class OrderReceipt(BaseModel):
    id: int
    customer_name: str
    email: str
    total_cents: int
    status: str
    items: list[OrderLine]


@js
class CheckoutResult(BaseModel):
    receipt: OrderReceipt
    checkout_url: str


@js
class OrderSummary(ModelSchema):
    id: int
    placed_on: date
    item_count: int

    class Meta:
        model = db.Order
        fields = ("total_cents", "status")


@js
class InventoryChange(BaseModel):
    product_id: int
    inventory: int = Field(ge=0)


@js
class AccountSummary(BaseModel):
    id: int
    order_count: int
    total_cents: int


@js
class VisitorEvent(ModelSchema):
    id: int
    occurred_on: date
    occurred_time: str

    class Meta:
        model = db.VisitorEvent
        fields = ("path", "source", "region", "device")


@js
class TrafficSummary(BaseModel):
    total: int
    labels: list[str]
    values: list[int]
