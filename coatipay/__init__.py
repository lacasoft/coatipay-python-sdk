"""
CoatiPay Python SDK
The open payment network. No fees. No gatekeepers.
"""
from .client import CoatiPay
from .errors import CoatiPayError, CoatiPaySDKError
from .x402 import X402Middleware

__all__ = ["CoatiPay", "CoatiPayError", "CoatiPaySDKError", "X402Middleware"]
__version__ = "0.1.1"
