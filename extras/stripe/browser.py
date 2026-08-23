"""Typed declarations for Stripe.js and its current payment widgets."""

from collections.abc import Awaitable, Callable
from typing import Final, Literal, NotRequired, TypedDict, overload

from pyjs import JS, js
from pyjs.web.dom import Element


class StripeConstructorOptions(TypedDict):
    stripeAccount: NotRequired[str]
    apiVersion: NotRequired[str]
    locale: NotRequired[str]
    betas: NotRequired[list[str]]


class ElementsOptions(TypedDict):
    clientSecret: NotRequired[str]
    mode: NotRequired[Literal["payment", "setup", "subscription"]]
    amount: NotRequired[int]
    currency: NotRequired[str]
    locale: NotRequired[str]
    appearance: NotRequired[object]


class ElementOptions(TypedDict):
    mode: NotRequired[Literal["billing", "shipping"]]
    layout: NotRequired[str]
    defaultValues: NotRequired[object]
    fields: NotRequired[object]
    wallets: NotRequired[object]
    terms: NotRequired[object]


class ConfirmParams(TypedDict):
    return_url: NotRequired[str]
    receipt_email: NotRequired[str]


class ConfirmPaymentOptions(TypedDict):
    elements: NotRequired[StripeElements]
    clientSecret: NotRequired[str]
    confirmParams: NotRequired[ConfirmParams]
    redirect: NotRequired[Literal["always", "if_required"]]


class EmbeddedCheckoutOptions(TypedDict):
    clientSecret: NotRequired[str]
    fetchClientSecret: NotRequired[Callable[[], Awaitable[str]]]
    onComplete: NotRequired[Callable[[], None]]


class StripeError(TypedDict):
    type: str
    message: str
    code: NotRequired[str]
    decline_code: NotRequired[str]


class PaymentResult(TypedDict):
    error: NotRequired[StripeError]
    paymentIntent: NotRequired[object]


class ElementChangeEvent(TypedDict):
    elementType: str
    empty: bool
    complete: bool
    error: NotRequired[StripeError]


ElementType = Literal[
    "address",
    "expressCheckout",
    "linkAuthentication",
    "payment",
    "paymentMethodMessaging",
]


@js.native
class StripeElement:
    def mount(self, target: str | Element) -> None: ...

    def unmount(self) -> None: ...

    def destroy(self) -> None: ...

    def focus(self) -> None: ...

    def blur(self) -> None: ...

    def clear(self) -> None: ...

    def on(
        self,
        event_type: Literal["change", "ready", "focus", "blur", "escape"],
        handler: Callable[[ElementChangeEvent], None],
    ) -> None: ...


@js.native
class PaymentElement(StripeElement): ...


@js.native
class AddressElement(StripeElement): ...


@js.native
class ExpressCheckoutElement(StripeElement): ...


@js.native
class LinkAuthenticationElement(StripeElement): ...


@js.native
class StripeElements:
    @overload
    def create(
        self,
        element_type: Literal["payment"],
        options: ElementOptions,
    ) -> PaymentElement: ...

    @overload
    def create(
        self,
        element_type: Literal["address"],
        options: ElementOptions,
    ) -> AddressElement: ...

    @overload
    def create(
        self,
        element_type: Literal["expressCheckout"],
        options: ElementOptions,
    ) -> ExpressCheckoutElement: ...

    @overload
    def create(
        self,
        element_type: Literal["linkAuthentication"],
        options: ElementOptions,
    ) -> LinkAuthenticationElement: ...

    def create(
        self,
        element_type: ElementType,
        options: ElementOptions,
    ) -> StripeElement: ...

    async def update(self, options: ElementsOptions) -> None: ...

    async def submit(self) -> object: ...

    async def fetchUpdates(self) -> object: ...


@js.native
class EmbeddedCheckout:
    def mount(self, target: str | Element) -> None: ...

    def unmount(self) -> None: ...

    def destroy(self) -> None: ...


@js.native
class StripeClient:
    def elements(self, options: ElementsOptions) -> StripeElements: ...

    async def confirmPayment(
        self,
        options: ConfirmPaymentOptions,
    ) -> PaymentResult: ...

    async def initEmbeddedCheckout(
        self,
        options: EmbeddedCheckoutOptions,
    ) -> EmbeddedCheckout: ...


@js.native
def Stripe(
    publishable_key: str,
    options: StripeConstructorOptions | None = None,
) -> StripeClient: ...


STRIPE_JS_URL: Final[JS[str]] = "https://js.stripe.com/v3/"
PRICING_TABLE_JS_URL: Final[JS[str]] = "https://js.stripe.com/v3/pricing-table.js"
