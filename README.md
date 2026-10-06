# coatipay — Python SDK

The CoatiPay Python SDK — **Stripe-compatible payments for the open web**.
Accept **USDC on Base** with no gatekeepers: gasless settlement (ERC-3009), webhooks, and
x402 micropayments. 1.5% protocol fee (1.05% nodeit / 0.45% treasury), settled trustlessly on-chain.

- ⛽ **Gasless for payers** — they sign an ERC-3009 authorization; the nodeit pays the gas.
- 🧩 **Stripe-like DX** — `payment_intents.create`, `webhooks.verify`.
- 🌐 **Open network** — no lock-in: any nodeit can settle your payments, and anyone can run one.

## Install

```bash
pip install coatipay-sdk
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
            # Safe to retry: the same key with the same parameters returns the same intent.
            idempotency_key="order_123",
        )
        print(intent["id"], intent["status"])  # "pi_…", "created"


asyncio.run(main())
```

Other payment-intent methods: `retrieve(id)`, `list(limit=10)`, `cancel(id)`.

## Gasless settlement with ERC-3009

Payers authorize USDC transfers off-chain with an EIP-712 signature. The nodeit
pays the gas to settle on-chain.

The authorization's `nonce` **is** the intent being paid: you pass the intent id
the API gave you (`pi_…`) and the SDK derives the on-chain form. The contract
requires that binding, so a payer's signature can only ever settle that one
intent — the nodeit relaying it cannot redirect the payment elsewhere.

```python
from coatipay.eip712 import sign_authorization, serialize_authorization

intent = await relay.payment_intents.create(amount=1_000_000, currency="usdc", chain="base")

auth = sign_authorization(
    payer="0xPayerAddress...",
    amount=1_000_000,                         # 1.00 USDC — must match the intent
    settlement_hub="0xSettlementHubAddress...",
    chain="base",
    private_key="0x...",                      # payer private key — server-side demo only
    intent_id=intent["id"],                   # "pi_…" — the nonce is derived from it
)

await relay.payment_intents.submit_authorization(intent["id"], auth)
```

For batch settlement, pass a list of `{"intent_id": ..., "authorization": auth}`
items to `relay.payment_intents.submit_authorization_batch(items)` (max 50 per batch).

If you build the authorization yourself — a browser wallet signing the typed
data, for instance — derive the nonce with the same helper the SDK uses, so both
sides agree on the value the contract checks:

```python
from coatipay import intent_id_to_bytes32

nonce = intent_id_to_bytes32(intent["id"])  # keccak256(utf8("pi_…"))
```

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
from coatipay import WebhookSignatureError

try:
    event = relay.webhooks.verify(
        payload,                                  # the RAW request body (str)
        signature=request.headers["x-signature"],
        secret="whsec_...",
    )
except WebhookSignatureError as e:
    return Response(status_code=400, content=e.reason)

# At least once and in no particular order: deduplicate by event["id"].
if event["type"] == "payment_intent.settled":
    fulfill_order(event["data"]["metadata"]["order_id"])
```

- `verify` checks the HMAC-SHA256 signature in constant time and rejects a timestamp more
  than 5 minutes away from now (replay protection): `tolerance=` changes it, in seconds.
- On failure it raises `WebhookSignatureError` (a `ValueError`) with a `reason`:
  `malformed_header`, `timestamp_out_of_tolerance` or `no_matching_signature`.
- Events: `payment_intent.created`, `payment_intent.settled`, `payment_intent.expired`,
  `payment_intent.cancelled`.
- **Rotating the secret.** `rotate_secret` returns a new secret — once: store it. The
  previous one keeps signing next to it for 24 hours (`keep_previous_for=`, in seconds, up
  to 7 days), and `verify` accepts either, so you change the secret on your server without
  dropping a delivery. If a secret leaked, `keep_previous_for=0` retires it at once.

  ```python
  rotated = await relay.webhooks.rotate_secret("we_…")  # rotated["secret"]
  await relay.webhooks.rotate_secret("we_…", keep_previous_for=0)  # leaked: stop now
  ```
- **Deliveries that exhausted their retries** stay in a dead-letter queue:

  ```python
  dead = await relay.webhooks.list_dead_letters(limit=20)
  await relay.webhooks.replay_dead_letter(dead["data"][0]["id"])  # same event, same id
  ```

## Errors

```python
from coatipay import CoatiPaySDKError, NetworkError

try:
    await relay.payment_intents.create(
        amount=amount, currency="usdc", chain="base", idempotency_key=order_id
    )
except NetworkError as e:
    # No CoatiPay answer (e.status: the HTTP status, or None). Whether it took effect is
    # unknown: retrying with the same idempotency_key returns the same intent.
    ...
except CoatiPaySDKError as e:
    print(e.code, e.message, e.param, e.doc_url)
```

Everything a call raises is a `CoatiPaySDKError`, with `code`, `message`, `param` and
`doc_url` (the code's page at [coatipay.com/docs/errors](https://coatipay.com/docs/errors/)).
The class tells the kind: `AuthError`, `ValidationError`, `RoutingError`, `PaymentError`,
`RateLimitError`, or the base class for the rest and for a code this version does not know.
`NetworkError` is one too, so catch it first. The same classes and rules in the JS and
PHP SDKs.

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
- Source: [`coatipay-python-sdk`](https://github.com/lacasoft/coatipay-python-sdk)
- License: Apache-2.0
