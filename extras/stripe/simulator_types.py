"""Shared types and constants for the local Stripe simulator."""

from dataclasses import dataclass

SUCCESS_CARD = "4242424242424242"
DECLINED_CARD = "4000000000000002"
AUTHENTICATION_CARD = "4000002500003155"
RENEWAL_FAILURE_CARD = "4000000000000341"
RENEWAL_BEHAVIORS = {
    "success",
    "soft_decline",
    "hard_decline",
    "authentication_required",
}


@dataclass(frozen=True)
class SimulatorOptions:
    public_url: str
    webhook_url: str = ""
    webhook_secret: str = "whsec_local"
    api_key: str = "sk_test_local"
    product_id: str = "prod_local_membership"
    price_id: str = "price_local_monthly"
    product_name: str = "Example membership"
    unit_amount: int = 500
    currency: str = "usd"
    max_payment_attempts: int = 3

    def __post_init__(self) -> None:
        if self.max_payment_attempts < 1:
            raise ValueError("max_payment_attempts must be at least 1")


class SimulatorHTTPError(Exception):
    def __init__(self, status: int, error_type: str, message: str):
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.message = message


def status_text(status: int) -> str:
    return {
        200: "OK",
        400: "Bad Request",
        401: "Unauthorized",
        402: "Payment Required",
        404: "Not Found",
    }.get(status, "OK")
