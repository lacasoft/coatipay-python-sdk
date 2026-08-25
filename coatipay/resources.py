"""CoatiPay API resource classes."""
from __future__ import annotations

import httpx

from .eip712 import (
    SignedAuthorization,
    build_authorization_typed_data,
    serialize_authorization,
    sign_authorization,
)
from .errors import CoatiPaySDKError

MAX_BATCH_SIZE = 50


async def _request(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    response = await client.request(method, f"/v1{path}", **kwargs)
    data = response.json()
    if not response.is_success:
        err = data.get("error", {})
        raise CoatiPaySDKError(
            code=err.get("code", "unknown_error"),
            message=err.get("message", "Unknown error"),
            param=err.get("param"),
            doc_url=err.get("doc_url", "https://docs.coatipay.com"),
        )
    return data


class PaymentIntents:
    """
    Operations on payment intents.

    Example:
        intent = await relay.payment_intents.create(
            amount=10_000_000, currency="usdc", chain="base",
            metadata={"order_id": "123"}
        )
    """

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def create(self, amount: int, currency: str, chain: str, **kwargs) -> dict:
        return await _request(
            self._client, "POST", "/payment_intents",
            json={"amount": amount, "currency": currency, "chain": chain, **kwargs},
        )

    async def retrieve(self, intent_id: str) -> dict:
        return await _request(self._client, "GET", f"/payment_intents/{intent_id}")

    async def cancel(self, intent_id: str) -> dict:
        return await _request(self._client, "POST", f"/payment_intents/{intent_id}/cancel")

    async def list(self, limit: int = 10, starting_after: str | None = None) -> dict:
        params = {"limit": limit}
        if starting_after:
            params["starting_after"] = starting_after
        return await _request(self._client, "GET", "/payment_intents", params=params)

    # ── Gasless settlement (ERC-3009 / ADR-003) ─────────────────────────

    def build_authorization_typed_data(
        self,
        payer: str,
        amount: int,
        settlement_hub: str,
        chain: str,
        *,
        nonce: str | None = None,
        valid_after: int | None = None,
        valid_before: int | None = None,
    ) -> dict:
        """Build the EIP-712 typed data for USDC ReceiveWithAuthorization."""
        return build_authorization_typed_data(
            payer=payer,
            amount=amount,
            settlement_hub=settlement_hub,
            chain=chain,  # type: ignore[arg-type]
            nonce=nonce,
            valid_after=valid_after,
            valid_before=valid_before,
        )

    def sign_authorization(
        self,
        payer: str,
        amount: int,
        settlement_hub: str,
        chain: str,
        private_key: str,
        *,
        nonce: str | None = None,
        valid_after: int | None = None,
        valid_before: int | None = None,
    ) -> SignedAuthorization:
        """Build and sign a ReceiveWithAuthorization message."""
        return sign_authorization(
            payer=payer,
            amount=amount,
            settlement_hub=settlement_hub,
            chain=chain,  # type: ignore[arg-type]
            private_key=private_key,
            nonce=nonce,
            valid_after=valid_after,
            valid_before=valid_before,
        )

    async def submit_authorization(
        self,
        intent_id: str,
        authorization: SignedAuthorization,
    ) -> dict:
        """Submit a signed authorization for settlement."""
        return await _request(
            self._client,
            "POST",
            f"/payment_intents/{intent_id}/authorize",
            json=serialize_authorization(authorization),
        )

    async def submit_authorization_batch(
        self,
        items: list[dict],
    ) -> dict:
        """Submit multiple signed authorizations in one request."""
        if len(items) == 0:
            return {"results": [], "queued": 0, "rejected": 0}
        if len(items) > MAX_BATCH_SIZE:
            raise ValueError(
                f"Batch too large: {len(items)} authorizations (max {MAX_BATCH_SIZE})"
            )
        return await _request(
            self._client,
            "POST",
            "/payment_intents/batch/authorize",
            json={
                "items": [
                    {
                        "intent_id": item["intent_id"],
                        "authorization": serialize_authorization(item["authorization"]),
                    }
                    for item in items
                ]
            },
        )


class Webhooks:
    """
    Webhook endpoint management and signature verification.

    Example:
        relay.webhooks.verify(payload, signature, secret)
    """

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    def verify(self, payload: str, signature: str, secret: str) -> dict:
        import hmac, hashlib, json, time
        parts = {p.split("=")[0]: p.split("=")[1] for p in signature.split(",")}
        ts, sig = parts.get("t", ""), parts.get("v1", "")

        # Reject if timestamp is older than 5 minutes to prevent replay attacks
        try:
            ts_int = int(ts)
        except (ValueError, TypeError):
            raise ValueError("Invalid webhook timestamp")
        if abs(time.time() - ts_int) > 300:
            raise ValueError("Webhook timestamp too old")

        expected = hmac.new(
            secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError("Webhook signature verification failed")
        return json.loads(payload)

    async def register(self, url: str, events: list[str]) -> dict:
        return await _request(
            self._client, "POST", "/webhooks", json={"url": url, "events": events}
        )
