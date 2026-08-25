"""Tests for the x402 middleware."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from coatipay import CoatiPay, X402Middleware

USDC_BASE_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


@pytest.fixture
def relay() -> CoatiPay:
    return CoatiPay(
        api_key="sk_live_x402test",
        base_url="https://api.test.coatipay.com",
        merchant_wallet="0xMerchantWallet123",
    )


def _mock_verify_response(relay: CoatiPay, status_code: int) -> None:
    post_mock = AsyncMock()
    response_mock = AsyncMock()
    response_mock.is_success = 200 <= status_code < 300
    response_mock.status_code = status_code
    # `json()` is sync on httpx.Response; return a verified=true body for 2xx.
    response_mock.json = lambda: {"verified": 200 <= status_code < 300}
    post_mock.return_value = response_mock
    relay._client.post = post_mock


def test_asgi_middleware_returns_402_when_no_payment_header(relay: CoatiPay) -> None:
    def homepage(request):
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/protected", homepage)])
    app.add_middleware(
        X402Middleware,
        client=relay,
        price=5_000,
        currency="usdc",
        chain="base",
        description="Premium API access",
    )

    client = TestClient(app)
    response = client.get("/protected")

    assert response.status_code == 402
    body = response.json()
    assert body["x402Version"] == 1
    assert len(body["accepts"]) == 1
    option = body["accepts"][0]
    assert option["scheme"] == "exact"
    assert option["network"] == "base"
    assert option["maxAmountRequired"] == "5000"
    assert option["description"] == "Premium API access"
    assert option["payTo"] == "0xMerchantWallet123"
    assert option["asset"] == USDC_BASE_ADDRESS
    assert option["maxTimeoutSeconds"] == 300
    assert option["mimeType"] == "application/json"


def test_asgi_middleware_uses_default_description(relay: CoatiPay) -> None:
    def homepage(request):
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        X402Middleware,
        client=relay,
        price=1_000,
        currency="usdc",
        chain="base",
    )

    response = TestClient(app).get("/")
    assert response.json()["accepts"][0]["description"] == "API access"


def test_asgi_middleware_passes_through_when_payment_valid(relay: CoatiPay) -> None:
    _mock_verify_response(relay, 200)

    def homepage(request):
        return JSONResponse({"data": "secret"})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        X402Middleware,
        client=relay,
        price=1_000,
        currency="usdc",
        chain="base",
    )

    response = TestClient(app).get("/", headers={"x-payment": "validpayment"})
    assert response.status_code == 200
    assert response.json()["data"] == "secret"
    relay._client.post.assert_awaited_once_with(
        "/v1/x402/verify",
        json={"payment": "validpayment", "amount": 1_000, "chain": "base"},
    )


def test_asgi_middleware_returns_402_when_verification_fails(relay: CoatiPay) -> None:
    _mock_verify_response(relay, 402)

    def homepage(request):
        return JSONResponse({"data": "secret"})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        X402Middleware,
        client=relay,
        price=1_000,
        currency="usdc",
        chain="base",
    )

    response = TestClient(app).get("/", headers={"x-payment": "badpayment"})
    assert response.status_code == 402
    assert response.json()["error"] == "Payment verification failed"


def test_asgi_middleware_returns_402_when_network_error(relay: CoatiPay) -> None:
    relay._client.post = AsyncMock(side_effect=RuntimeError("network error"))

    def homepage(request):
        return JSONResponse({"data": "secret"})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        X402Middleware,
        client=relay,
        price=1_000,
        currency="usdc",
        chain="base",
    )

    response = TestClient(app).get("/", headers={"x-payment": "somepayment"})
    assert response.status_code == 402


def test_dispatch_helper_via_base_http_middleware(relay: CoatiPay) -> None:
    _mock_verify_response(relay, 200)

    async def homepage(request):
        return JSONResponse({"data": "secret"})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        BaseHTTPMiddleware,
        dispatch=relay.x402.middleware(
            price=1_000,
            currency="usdc",
            chain="base",
        ),
    )

    response = TestClient(app).get("/", headers={"x-payment": "validpayment"})
    assert response.status_code == 200


def test_pay_to_is_empty_without_merchant_wallet() -> None:
    relay_no_wallet = CoatiPay(api_key="sk_live_x402test")

    def homepage(request):
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        X402Middleware,
        client=relay_no_wallet,
        price=1_000,
        currency="usdc",
        chain="base",
    )

    response = TestClient(app).get("/")
    assert response.json()["accepts"][0]["payTo"] == ""


def test_resource_url_is_included_in_challenge(relay: CoatiPay) -> None:
    def homepage(request):
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/v1/resource/123", homepage)])
    app.add_middleware(
        X402Middleware,
        client=relay,
        price=500,
        currency="usdc",
        chain="base",
    )

    response = TestClient(app).get("/v1/resource/123")
    assert response.json()["accepts"][0]["resource"] == "http://testserver/v1/resource/123"


def test_advertises_base_mainnet_usdc_domain(relay: CoatiPay) -> None:
    def homepage(request):
        return PlainTextResponse("OK")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(X402Middleware, client=relay, price=1_000, currency="usdc", chain="base")
    option = TestClient(app).get("/").json()["accepts"][0]
    # Base mainnet: asset = mainnet USDC, domain name = "USD Coin" (NOT "USDC")
    assert option["asset"] == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    assert option["extra"] == {"name": "USD Coin", "version": "2"}


def test_rejects_unsupported_x402_chain() -> None:
    # x402 is Base-only at the facilitator → configuring another chain raises
    # instead of building a challenge that could never be verified.
    from coatipay.x402 import X402MiddlewareOptions

    with pytest.raises(ValueError, match="only supported"):
        X402MiddlewareOptions(price=1_000, currency="usdc", chain="base-sepolia")
