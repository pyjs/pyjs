from django.db import models


class Product(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=240)
    cents = models.PositiveIntegerField()
    symbol = models.CharField(max_length=8)
    tone = models.CharField(max_length=20)
    inventory = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("id",)

    def __str__(self) -> str:
        return self.name


class Review(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    author_name = models.CharField(max_length=80)
    rating = models.PositiveSmallIntegerField()
    body = models.CharField(max_length=320)
    created_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.PENDING,
    )

    class Meta:
        ordering = ("-created_at", "-id")

    @property
    def product_name(self) -> str:
        return self.product.name


class Order(models.Model):
    class Status(models.TextChoices):
        READY = "ready", "Ready for payment"
        PAID = "paid", "Paid"

    customer_name = models.CharField(max_length=120)
    email = models.EmailField()
    total_cents = models.PositiveIntegerField()
    checkout_key = models.CharField(max_length=64, null=True, unique=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.READY)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def placed_on(self):
        return self.created_at.date()

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items.all())


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_cents = models.PositiveIntegerField()


class VisitorEvent(models.Model):
    path = models.CharField(max_length=160)
    source = models.CharField(max_length=80)
    region = models.CharField(max_length=80)
    device = models.CharField(max_length=40)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ("-occurred_at", "-id")

    @property
    def occurred_on(self):
        return self.occurred_at.date()

    @property
    def occurred_time(self) -> str:
        return self.occurred_at.strftime("%H:%M UTC")
