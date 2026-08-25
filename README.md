# coatipay — Python SDK

The CoatiPay Python SDK — **Stripe-compatible payments for the open web**.
Accept **USDC on Base** with no gatekeepers: gasless settlement (ERC-3009), webhooks, and
x402 micropayments. ~1% protocol fee (0.7% nodeit / 0.3% treasury), settled trustlessly on-chain.

- ⛽ **Gasless for payers** — they sign an ERC-3009 authorization; the nodeit pays the gas.
- 🧩 **Stripe-like DX** — `payment_intents.create`, `webhooks.verify`.
- 🌐 **Open network** — no lock-in, self-host or use any nodeit.

## Install

```bash
pip install coatipay
```

Requires Python ≥ 3.11. Depends on `httpx` and `pydantic`.

## Quick start

The client is **async** (built on `httpx.AsyncClient`):

```python
import asyncio
from coatipay import CoatiPay


async def main():
    # Use a SECRET key, server-side only — never ship it to a client.
    async with CoatiPay(api_key="sk_live_...") as relay:
        intent = await relay.payment_intents.create(
            amount=10_000_000,            # 10.00 USDC (6 decimals → 1 USDC = 1_000_000)
            currency="usdc",
            chain="base",
            metadata={"order_id": "123"},
        )
        print(intent["id"], intent["status"])  # "pi_…", "created"


asyncio.run(main())
```

Other payment-intent methods: `retrieve(id)`, `list(limit=10)`, `cancel(id)`.

## Gasless settlement with ERC-3009

Payers authorize USDC transfers off-chain with an EIP-712 signature. The nodeit
pays the gas to settle on-chain.

```python
from coatipay.eip712 import sign_authorization, serialize_authorization

auth = sign_authorization(
    payer="0xPayerAddress...",
    amount=1_000_000,                         # 1.00 USDC
    settlement_hub="0xSettlementHubAddress...",
    chain="base",
    private_key="0x...",                      # payer private key — server-side demo only
)

await relay.payment_intents.submit_authorization("pi_...", auth)
```

For batch settlement, pass a list of `{"intent_id": ..., "authorization": auth}`
items to `relay.payment_intents.submit_authorization_batch(items)` (max 50 per batch).

## x402 micropayments

Protect a FastAPI / Starlette route with a 402 payment gate.

```python
from fastapi import FastAPI
from coatipay import CoatiPay, X402Middleware

relay = CoatiPay(api_key="sk_live_...", merchant_wallet="0xMerchantWallet...")

app = FastAPI()
app.add_middleware(
    X402Middleware,
    client=relay,
    price=1_000,          # 0.001 USDC
    currency="usdc",
    chain="base",
    description="Premium API access",
)

@app.get("/premium")
async def premium():
    return {"data": "exclusive"}
```

Or use the dispatch helper with Starlette's `BaseHTTPMiddleware`:

```python
from starlette.middleware.base import BaseHTTPMiddleware

app.add_middleware(
    BaseHTTPMiddleware,
    dispatch=relay.x402.middleware(price=1_000, currency="usdc", chain="base"),
)
```

## Webhooks

```python
event = relay.webhooks.verify(
    payload,                                  # raw request body (str)
    signature=request.headers["x-signature"],
    secret="whsec_...",
)
if event["type"] == "payment_intent.settled":
    fulfill_order(event["data"]["metadata"]["order_id"])
```

## Configuration

```python
CoatiPay(
    api_key="sk_live_...",                  # required — secret key, server-side only
    base_url="https://api.coatipay.com",  # optional — your CoatiPay API host
    timeout=30.0,                           # optional — seconds
    merchant_wallet="0x...",                # optional — receives x402 payments
)
```

## Links

- Repo, docs & protocol spec: https://github.com/lacasoft/coatipay-protocol
- Source: [`packages/sdk-python`](https://github.com/lacasoft/coatipay-protocol/tree/master/packages/sdk-python)
- License: Apache-2.0
