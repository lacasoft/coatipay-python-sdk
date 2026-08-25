"""CoatiPay main client."""
from __future__ import annotations
import httpx
from .resources import PaymentIntents, Webhooks
from .x402 import X402


class CoatiPay:
    """
    CoatiPay API client.

    Example:
        relay = CoatiPay(api_key="sk_live_xxx")
        intent = await relay.payment_intents.create(
            amount=10_000_000, currency="usdc", chain="base"
        )
    """

    BASE_URL = "https://api.coatipay.com"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 30.0,
        merchant_wallet: str | None = None,
    ):
        if not api_key:
            raise ValueError("CoatiPay: api_key is required")
        self._merchant_wallet = merchant_wallet
        self._client = httpx.AsyncClient(
            base_url=base_url or self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "CoatiPay-Version": "0.1",
            },
            timeout=timeout,
        )
        self.payment_intents = PaymentIntents(self._client)
        self.webhooks = Webhooks(self._client)
        self.x402 = X402(self)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "CoatiPay":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
