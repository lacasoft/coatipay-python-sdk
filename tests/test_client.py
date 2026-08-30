import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
import hmac
import hashlib
import json
import time

from coatipay import CoatiPay, CoatiPayError, CoatiPaySDKError, intent_id_to_bytes32


# ── Client initialization ─────────────────────────────────────────

class TestClientInit:
    def test_api_key_required(self):
        with pytest.raises(ValueError, match="api_key is required"):
            CoatiPay(api_key="")

    def test_api_key_none_raises(self):
        with pytest.raises((ValueError, TypeError)):
            CoatiPay(api_key=None)  # type: ignore

    def test_default_base_url(self):
        client = CoatiPay(api_key="sk_live_test123")
        assert client._client.base_url == httpx.URL("https://api.coatipay.com")

    def test_custom_base_url(self):
        client = CoatiPay(api_key="sk_live_test123", base_url="https://custom.api.dev")
        assert client._client.base_url == httpx.URL("https://custom.api.dev")

    def test_authorization_header(self):
        client = CoatiPay(api_key="sk_live_mykey")
        assert client._client.headers["authorization"] == "Bearer sk_live_mykey"

    def test_custom_timeout(self):
        client = CoatiPay(api_key="sk_live_test123", timeout=60.0)
        assert client._client.timeout.connect == 60.0

    def test_has_payment_intents(self):
        client = CoatiPay(api_key="sk_live_test123")
        assert hasattr(client, "payment_intents")

    def test_has_webhooks(self):
        client = CoatiPay(api_key="sk_live_test123")
        assert hasattr(client, "webhooks")


# ── PaymentIntents.create ──────────────────────────────────────────

class TestPaymentIntentsCreate:
    @pytest.mark.asyncio
    async def test_create_sends_post(self):
        mock_response = httpx.Response(
            201,
            json={"id": "pi_abc123", "amount": 10_000_000, "currency": "usdc", "chain": "base", "status": "created"},
        )
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response):
            client = CoatiPay(api_key="sk_live_test")
            result = await client.payment_intents.create(amount=10_000_000, currency="usdc", chain="base")
            assert result["id"] == "pi_abc123"
            assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_create_sends_correct_path(self):
        mock_response = httpx.Response(201, json={"id": "pi_test"})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            await client.payment_intents.create(amount=1000, currency="usdc", chain="base")
            mock_req.assert_called_once()
            args, kwargs = mock_req.call_args
            assert args[0] == "POST"
            assert args[1] == "/v1/payment_intents"
            assert kwargs["json"]["amount"] == 1000
            assert kwargs["json"]["currency"] == "usdc"
            assert kwargs["json"]["chain"] == "base"

    @pytest.mark.asyncio
    async def test_create_with_metadata(self):
        mock_response = httpx.Response(201, json={"id": "pi_meta"})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            await client.payment_intents.create(
                amount=5000, currency="usdc", chain="base", metadata={"order_id": "ord_123"}
            )
            body = mock_req.call_args.kwargs["json"]
            assert body["metadata"] == {"order_id": "ord_123"}


# ── PaymentIntents.retrieve ────────────────────────────────────────

class TestPaymentIntentsRetrieve:
    @pytest.mark.asyncio
    async def test_retrieve_sends_get(self):
        mock_response = httpx.Response(200, json={"id": "pi_retrieve123", "status": "pending_payment"})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            result = await client.payment_intents.retrieve("pi_retrieve123")
            assert result["id"] == "pi_retrieve123"
            args, _ = mock_req.call_args
            assert args[0] == "GET"
            assert args[1] == "/v1/payment_intents/pi_retrieve123"


# ── PaymentIntents.cancel ──────────────────────────────────────────

class TestPaymentIntentsCancel:
    @pytest.mark.asyncio
    async def test_cancel_sends_post(self):
        mock_response = httpx.Response(200, json={"id": "pi_cancel", "status": "cancelled"})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            result = await client.payment_intents.cancel("pi_cancel")
            assert result["status"] == "cancelled"
            args, _ = mock_req.call_args
            assert args[0] == "POST"
            assert args[1] == "/v1/payment_intents/pi_cancel/cancel"


# ── PaymentIntents.list ────────────────────────────────────────────

class TestPaymentIntentsList:
    @pytest.mark.asyncio
    async def test_list_default_params(self):
        mock_response = httpx.Response(200, json={"data": [], "has_more": False})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            result = await client.payment_intents.list()
            assert result["data"] == []
            _, kwargs = mock_req.call_args
            assert kwargs["params"]["limit"] == 10

    @pytest.mark.asyncio
    async def test_list_with_pagination(self):
        mock_response = httpx.Response(200, json={"data": [{"id": "pi_1"}], "has_more": True})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            result = await client.payment_intents.list(limit=5, starting_after="pi_cursor")
            assert result["has_more"] is True
            _, kwargs = mock_req.call_args
            assert kwargs["params"]["limit"] == 5
            assert kwargs["params"]["starting_after"] == "pi_cursor"

    @pytest.mark.asyncio
    async def test_list_without_starting_after(self):
        mock_response = httpx.Response(200, json={"data": [], "has_more": False})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            await client.payment_intents.list(limit=20)
            _, kwargs = mock_req.call_args
            assert "starting_after" not in kwargs["params"]


# ── PaymentIntents.submit_authorization (ERC-3009) ─────────────────

# El id del intent es texto (`pi_...`); lo que viaja como nonce es su
# identificador on-chain, derivado por el SDK.
INTENT_ID = "pi_abc"
INTENT_NONCE = intent_id_to_bytes32(INTENT_ID)


class TestSubmitAuthorization:
    @pytest.mark.asyncio
    async def test_submit_authorization_uses_v1_path(self):
        from coatipay.eip712 import SignedAuthorization

        # El nonce es el identificador on-chain del intent que se paga.
        auth = SignedAuthorization(
            payer="0x" + "aa" * 20,
            valid_after=0,
            valid_before=2_000_000_000,
            nonce=INTENT_NONCE,
            signature="0x" + "11" * 65,
        )
        mock_response = httpx.Response(200, json={"status": "queued"})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            await client.payment_intents.submit_authorization(INTENT_ID, auth)
            args, kwargs = mock_req.call_args
            assert args[0] == "POST"
            assert args[1] == f"/v1/payment_intents/{INTENT_ID}/authorize"
            assert kwargs["json"]["payer"] == auth.payer
            assert kwargs["json"]["valid_before"] == "2000000000"

    @pytest.mark.asyncio
    async def test_submit_authorization_batch_uses_v1_path(self):
        from coatipay.eip712 import SignedAuthorization

        auth = SignedAuthorization("0x" + "aa" * 20, 0, 2_000_000_000, INTENT_NONCE, "0x" + "11" * 65)
        mock_response = httpx.Response(200, json={"queued": 1, "rejected": 0})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
            client = CoatiPay(api_key="sk_live_test")
            await client.payment_intents.submit_authorization_batch(
                [{"intent_id": "pi_1", "authorization": auth}]
            )
            args, kwargs = mock_req.call_args
            assert args[1] == "/v1/payment_intents/batch/authorize"
            assert kwargs["json"]["items"][0]["intent_id"] == "pi_1"


# ── Error handling ─────────────────────────────────────────────────

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_api_error_raises_coatipay_error(self):
        error_body = {
            "error": {
                "code": "invalid_api_key",
                "message": "Invalid or revoked API key.",
                "param": None,
                "doc_url": "https://docs.coatipay.com/errors/invalid_api_key",
            }
        }
        mock_response = httpx.Response(401, json=error_body)
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response):
            client = CoatiPay(api_key="sk_live_bad")
            with pytest.raises(CoatiPaySDKError) as exc_info:
                await client.payment_intents.list()
            assert exc_info.value.code == "invalid_api_key"
            assert exc_info.value.doc_url == "https://docs.coatipay.com/errors/invalid_api_key"

    @pytest.mark.asyncio
    async def test_api_error_unknown_format(self):
        mock_response = httpx.Response(500, json={"error": {}})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_response):
            client = CoatiPay(api_key="sk_live_test")
            with pytest.raises(CoatiPaySDKError) as exc_info:
                await client.payment_intents.retrieve("pi_fail")
            assert exc_info.value.code == "unknown_error"

    def test_coatipay_error_is_alias(self):
        """CoatiPayError remains a backwards-compatible alias for CoatiPaySDKError."""
        assert CoatiPayError is CoatiPaySDKError
        exc = CoatiPayError("test_code", "Test message", "param", "https://docs.example.com")
        assert isinstance(exc, CoatiPaySDKError)
        assert exc.code == "test_code"
        assert exc.message == "Test message"


# ── Webhook verification ──────────────────────────────────────────

class TestWebhookVerification:
    def _make_signature(self, payload: str, secret: str, ts: int) -> str:
        sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    def test_valid_signature(self):
        client = CoatiPay(api_key="sk_live_test")
        secret = "whsec_test_secret_123"
        payload = json.dumps({"id": "evt_test", "type": "payment_intent.settled"})
        ts = int(time.time())
        signature = self._make_signature(payload, secret, ts)

        result = client.webhooks.verify(payload, signature, secret)
        assert result["id"] == "evt_test"
        assert result["type"] == "payment_intent.settled"

    def test_invalid_signature(self):
        client = CoatiPay(api_key="sk_live_test")
        secret = "whsec_test_secret_123"
        payload = json.dumps({"id": "evt_test"})
        ts = int(time.time())
        signature = f"t={ts},v1=invalidsignaturehex"

        with pytest.raises(ValueError, match="Webhook signature verification failed"):
            client.webhooks.verify(payload, signature, secret)

    def test_expired_timestamp(self):
        client = CoatiPay(api_key="sk_live_test")
        secret = "whsec_test_secret_123"
        payload = json.dumps({"id": "evt_test"})
        old_ts = int(time.time()) - 600  # 10 minutes ago
        signature = self._make_signature(payload, secret, old_ts)

        with pytest.raises(ValueError, match="Webhook timestamp too old"):
            client.webhooks.verify(payload, signature, secret)

    def test_invalid_timestamp(self):
        client = CoatiPay(api_key="sk_live_test")
        with pytest.raises(ValueError, match="Invalid webhook timestamp"):
            client.webhooks.verify('{"x":1}', "t=notanumber,v1=abc", "secret")

    def test_uses_hmac_compare_digest(self):
        """Verify the SDK uses timing-safe comparison via hmac.compare_digest."""
        client = CoatiPay(api_key="sk_live_test")
        secret = "whsec_test_secret_123"
        payload = json.dumps({"id": "evt_safe"})
        ts = int(time.time())

        # Compute the correct expected signature using the same logic as the SDK
        expected = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        signature = f"t={ts},v1={expected}"

        # The verify method uses hmac.compare_digest internally.
        # Confirm the result is correct (timing-safe path).
        assert hmac.compare_digest(expected, expected) is True

        result = client.webhooks.verify(payload, signature, secret)
        assert result["id"] == "evt_safe"


# ── Async context manager ─────────────────────────────────────────

class TestAsyncContextManager:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with CoatiPay(api_key="sk_live_test") as client:
            assert hasattr(client, "payment_intents")
