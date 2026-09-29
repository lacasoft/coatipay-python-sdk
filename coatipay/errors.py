"""CoatiPay SDK errors."""
from __future__ import annotations

from typing import Literal

from ._catalogo import CATEGORIAS


class CoatiPaySDKError(Exception):
    """Everything an API call raises: the API's errors, and `NetworkError`
    when there was no CoatiPay answer. One `except` covers them all.

    Every error carries the `code`, the `message`, the failing field in
    `param` (when there is one) and its reference page in `doc_url`.
    """

    def __init__(self, code: str, message: str, param: str | None, doc_url: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.param = param
        self.doc_url = doc_url


CoatiPayError = CoatiPaySDKError


class AuthError(CoatiPaySDKError):
    """API key missing, revoked, or lacking permissions; or an invalid session or token."""


class ValidationError(CoatiPaySDKError):
    """Request parameters failed server-side validation."""


class RoutingError(CoatiPaySDKError):
    """No nodeit reachable to route the payment."""


class PaymentError(CoatiPaySDKError):
    """An x402 payment could not be verified, or was already used."""


class RateLimitError(CoatiPaySDKError):
    """Too many requests. Wait before retrying (the response carries `Retry-After`)."""


def doc_url(code: str) -> str:
    """The reference page of an error code."""
    return f"https://coatipay.com/docs/errors/{code}"


class NetworkError(CoatiPaySDKError):
    """The request got no CoatiPay answer: no response at all (network, DNS,
    timeout: `status` is None), or a response that is not a CoatiPay error (a
    proxy's HTML 502, a body that is not JSON: `status` is its HTTP status).

    Whether the request took effect is unknown: before retrying a write, check
    (or create with the same `idempotency_key`). Code `network_error`, set by
    the SDK, never sent by the API. Same rule as the JS and PHP SDKs (shared
    vectors: `errores.json`, `respuestas`). The original exception, if any, is
    the `__cause__`.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(
            code="network_error", message=message, param=None, doc_url=doc_url("network_error")
        )
        self.status = status


_CLASES: dict[str, type[CoatiPaySDKError]] = {
    "auth": AuthError,
    "validation": ValidationError,
    "routing": RoutingError,
    "payment": PaymentError,
    "rate_limit": RateLimitError,
}


def classify_error(code: str, message: str, param: str | None, doc_url: str) -> CoatiPaySDKError:
    """The narrowest error class for an API error code, by its catalog category.

    A code this version of the SDK does not know (a newer API) becomes a plain
    `CoatiPaySDKError`, never a crash. Same classes as the JS and PHP SDKs
    (shared vectors: `errores.json`).
    """
    clase = _CLASES.get(CATEGORIAS.get(code, ""), CoatiPaySDKError)
    return clase(code=code, message=message, param=param, doc_url=doc_url)


WebhookSignatureReason = Literal[
    "malformed_header", "timestamp_out_of_tolerance", "no_matching_signature"
]


class WebhookSignatureError(ValueError):
    """Raised by `webhooks.verify` when the request cannot be trusted.

    A `ValueError`, as the SDK raised before, now with a `reason`:
    `malformed_header`, `timestamp_out_of_tolerance` or `no_matching_signature`.
    """

    def __init__(self, reason: WebhookSignatureReason, message: str):
        super().__init__(message)
        self.reason = reason
