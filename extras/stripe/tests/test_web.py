from pyjs.web.ssr import render_html
from pyjs_extras.stripe.web import pricing_table, pricing_table_script, stripe_script


def test_pricing_table_renders_customer_context():
    source = render_html(
        pricing_table(
            "prctbl_test",
            "pk_test_123",
            customer_email="member@example.com",
            client_reference_id="42",
        )
    )
    assert source == (
        '<stripe-pricing-table pricing-table-id="prctbl_test" '
        'publishable-key="pk_test_123" customer-email="member@example.com" '
        'client-reference-id="42"></stripe-pricing-table>'
    )


def test_script_helpers_use_stripe_origin():
    assert render_html(stripe_script()) == (
        '<script src="https://js.stripe.com/v3/"> </script>'
    )
    assert render_html(pricing_table_script()) == (
        '<script async="" src="https://js.stripe.com/v3/pricing-table.js"> </script>'
    )
