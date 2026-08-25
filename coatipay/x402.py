"""x402 middleware for CoatiPay (FastAPI / Starlette)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .eip712 import USDC_ADDRESSES, USDC_DOMAIN_NAMES, USDC_DOMAIN_VERSION

if TYPE_CHECKING:
    from .client import CoatiPay


DEFAULT_DESCRIPTION = "API access"
MAX_TIMEOUT_SECONDS = 300
X402_VERSION = 1
SCHEME = "exact"
MIME_TYPE = "application/json"

# Chains the CoatiPay facilitator can verify x402 payments on. The API's
# /v1/x402/verify only accepts Base today, so advertising any other chain would
# build a 402 challenge that can never be verified. Expand when the API does.
SUPPORTED_X402_CHAINS = ("base",)


@dataclass
class X402MiddlewareOptions:
    """Options for the x402 payment gate.

    ``currency`` is part of the shared x402 options surface (parity with the
    JS/PHP SDKs); CoatiPay settles in USDC, which is advertised as the asset.
    """

    price: int
    currency: str
    chain: str
    description: str | None = None

    def __post_init__(self) -> None:
        if self.chain not in SUPPORTED_X402_CHAINS:
            supported = ", ".join(SUPPORTED_X402_CHAINS)
            raise ValueError(
                f"x402 is only supported on: {supported} (got {self.chain!r}). "
                "The CoatiPay facilitator verifies x402 payments on Base only."
            )


class X402Gate:
    """Shared logic: inspect X-PAYMENT header and either challenge or verify."""

    def __init__(self, client: CoatiPay, options: X402MiddlewareOptions) -> None:
        self._client = client
        self._options = options

    async def check(self, request: Request) -> dict | None:
        """Return a 402 body or None when the request may proceed."""
        payment_header = request.headers.get("x-payment")
        if not payment_header:
            return self._build_payment_required(str(request.url))

        if not await self._verify(payment_header):
            return {"error": "Payment verification failed"}

        return None

    def _build_payment_required(self, resource: str) -> dict:
        return {
            "x402Version": X402_VERSION,
            "accepts": [
                {
                    "scheme": SCHEME,
                    "network": self._options.chain,
                    "maxAmountRequired": str(self._options.price),
                    "resource": resource,
                    "description": self._options.description or DEFAULT_DESCRIPTION,
                    "mimeType": MIME_TYPE,
                    "payTo": self._client._merchant_wallet or "",
                    "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
                    # Derived from the chain (not hardcoded): USDC's address and
                    # EIP-712 domain name differ per chain (base → "USD Coin",
                    # base-sepolia → "USDC"). A wrong name makes the payer sign
                    # the wrong domain → USDC rejects the settlement.
                    "asset": USDC_ADDRESSES.get(self._options.chain, USDC_ADDRESSES["base"]),
                    "extra": {
                        "name": USDC_DOMAIN_NAMES.get(
                            self._options.chain, USDC_DOMAIN_NAMES["base"]
                        ),
                        "version": USDC_DOMAIN_VERSION,
                    },
                }
            ],
        }

    async def _verify(self, payment_header: str) -> bool:
        try:
            response = await self._client._client.post(
                "/v1/x402/verify",
                json={
                    "payment": payment_header,
                    "amount": self._options.price,
                    "chain": self._options.chain,
                },
            )
            # Require BOTH a 2xx and an explicit verified=true in the body, so a
            # future API response that is 2xx without verification can't slip a
            # request through.
            if not response.is_success:
                return False
            return response.json().get("verified") is True
        except Exception:
            # Network errors, non-2xx, or a malformed body → treat as unverified.
            return False


class X402Middleware:
    """ASGI middleware that requires an x402 payment header.

    Example (FastAPI / Starlette):

        from coatipay.x402 import X402Middleware

        app.add_middleware(
            X402Middleware,
            client=relay,
            price=1_000,
            currency="usdc",
            chain="base",
            description="Premium API access",
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        client: CoatiPay,
        price: int,
        currency: str,
        chain: str,
        description: str | None = None,
    ) -> None:
        self.app = app
        self.gate = X402Gate(
            client,
            X402MiddlewareOptions(price, currency, chain, description),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        challenge = await self.gate.check(request)
        if challenge is not None:
            response = JSONResponse(challenge, status_code=402)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class X402:
    """x402 resource exposed by ``CoatiPay``."""

    def __init__(self, client: CoatiPay) -> None:
        self._client = client

    def middleware(
        self,
        price: int,
        currency: str,
        chain: str,
        description: str | None = None,
    ) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
        """Return a Starlette ``BaseHTTPMiddleware`` dispatch function.

        Example:

            from starlette.middleware.base import BaseHTTPMiddleware

            app.add_middleware(
                BaseHTTPMiddleware,
                dispatch=relay.x402.middleware(price=1_000, currency="usdc", chain="base"),
            )
        """
        gate = X402Gate(
            self._client,
            X402MiddlewareOptions(price, currency, chain, description),
        )

        async def dispatch(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            challenge = await gate.check(request)
            if challenge is not None:
                return JSONResponse(challenge, status_code=402)
            return await call_next(request)

        return dispatch
