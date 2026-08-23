from pyjs import js
from pyjs.transpiler import bundle
from pyjs.web.dom import document
from pyjs_extras.stripe.browser import (
    ConfirmPaymentOptions,
    ElementOptions,
    ElementsOptions,
    EmbeddedCheckoutOptions,
    Stripe,
)


@js
async def stripe_elements():
    stripe = Stripe("pk_test_example")
    elements_options: ElementsOptions = {
        "clientSecret": "pi_secret_example",
    }
    elements = stripe.elements(elements_options)
    element_options: ElementOptions = {}
    payment = elements.create("payment", element_options)
    payment.mount(document.body)
    address_options: ElementOptions = {"mode": "billing"}
    elements.create("address", address_options).mount("#billing-address")
    elements.create("expressCheckout", element_options).mount("#express-checkout")
    elements.create("linkAuthentication", element_options).mount("#link-authentication")
    checkout_options: EmbeddedCheckoutOptions = {"clientSecret": "cs_secret_example"}
    checkout = await stripe.initEmbeddedCheckout(checkout_options)
    checkout.mount("#embedded-checkout")
    confirm_options: ConfirmPaymentOptions = {
        "elements": elements,
        "confirmParams": {"return_url": "https://example.test/complete"},
    }
    return await stripe.confirmPayment(confirm_options)


def test_stripe_js_elements_compile_to_native_calls():
    javascript, _ = bundle(stripe_elements, include_main=True)

    # The shared generated module scaffold is large; verify the native call surface.
    assert "Stripe('pk_test_example')" in javascript
    assert ".elements(" in javascript
    assert ".create('payment'" in javascript
    assert ".mount(document.body)" in javascript
    assert ".confirmPayment(" in javascript
    assert ".create('address'" in javascript
    assert ".create('expressCheckout'" in javascript
    assert ".create('linkAuthentication'" in javascript
    assert ".initEmbeddedCheckout(" in javascript
