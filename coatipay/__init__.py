"""
CoatiPay Python SDK
The open payment network: USDC on Base, non-custodial, no gatekeepers.
"""
from .client import CoatiPay
# Se exporta desde el paquete porque quien arma la autorización a mano (con su
# propia wallet, sin pasar por `sign_authorization`) necesita el mismo nonce que
# deriva el SDK; que lo calcule por su cuenta es justo el error que se quiere
# hacer imposible.
from .eip712 import intent_id_to_bytes32
from .errors import (
    AuthError,
    CoatiPayError,
    CoatiPaySDKError,
    NetworkError,
    PaymentError,
    RateLimitError,
    RoutingError,
    ValidationError,
    WebhookSignatureError,
    classify_error,
)
from .x402 import X402Middleware

__all__ = [
    "AuthError",
    "CoatiPay",
    "CoatiPayError",
    "CoatiPaySDKError",
    "NetworkError",
    "PaymentError",
    "RateLimitError",
    "RoutingError",
    "ValidationError",
    "WebhookSignatureError",
    "X402Middleware",
    "classify_error",
    "intent_id_to_bytes32",
]
__version__ = "0.1.4"
