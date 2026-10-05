"""CoatiPay API resource classes."""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

import httpx

from .eip712 import (
    SignedAuthorization,
    build_authorization_typed_data,
    serialize_authorization,
    sign_authorization,
)
from .errors import NetworkError, WebhookSignatureError, classify_error, doc_url

MAX_BATCH_SIZE = 50

# Default tolerance for the `t=` timestamp of a webhook signature: 5 minutes.
DEFAULT_TOLERANCE_SECONDS = 300

# One per status change of a payment intent. There is no `failed` event.
WebhookEventType = Literal[
    "payment_intent.created",
    "payment_intent.settled",
    "payment_intent.expired",
    "payment_intent.cancelled",
]


async def _request(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    # La misma regla en los tres SDK (vectores compartidos: errores.json,
    # `respuestas`). Sin respuesta, o una que no es de CoatiPay → NetworkError.
    try:
        response = await client.request(method, f"/v1{path}", **kwargs)
    except httpx.TimeoutException as e:
        raise NetworkError(f"Request timed out: {path}") from e
    except httpx.RequestError as e:
        raise NetworkError(f"Network error: {path}") from e

    # Un cuerpo que no es JSON no es una respuesta de CoatiPay, aunque sea un
    # 2xx: el 502 de un proxy es HTML.
    try:
        data = response.json()
    except ValueError as e:
        raise NetworkError(
            f"Response is not JSON (HTTP {response.status_code}): {path}",
            status=response.status_code,
        ) from e
    if response.is_success:
        return data

    # Un error de CoatiPay es un objeto cuyo `error` es un objeto con `code`
    # de texto no vacío. Lo demás (el error por defecto de Fastify, el JSON de
    # un proxy) no lo es.
    err = data.get("error") if isinstance(data, dict) else None
    code = err.get("code") if isinstance(err, dict) else None
    if not isinstance(code, str) or not code:
        raise NetworkError(
            f"Response is not a CoatiPay error (HTTP {response.status_code}): {path}",
            status=response.status_code,
        )
    # La clase más concreta según la categoría del código (AuthError,
    # ValidationError…); todas heredan de CoatiPaySDKError.
    raise classify_error(
        code=code,
        message=_texto(err, "message") or "Unknown error",
        param=_texto(err, "param"),
        doc_url=_texto(err, "doc_url") or doc_url(code),
    )


def _texto(err: dict, clave: str) -> str | None:
    valor = err.get(clave)
    return valor if isinstance(valor, str) else None


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

    async def create(
        self,
        amount: int,
        currency: str,
        chain: str,
        *,
        idempotency_key: str | None = None,
        **kwargs,
    ) -> dict:
        """Create a payment intent.

        `idempotency_key` makes it safe to retry: the same key with the same
        parameters returns the same intent instead of creating another one
        (and a different amount with the same key is an
        `idempotency_key_reused` error).
        """
        return await _request(
            self._client, "POST", "/payment_intents",
            json={"amount": amount, "currency": currency, "chain": chain, **kwargs},
            **({"headers": {"Idempotency-Key": idempotency_key}} if idempotency_key else {}),
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
        intent_id: str,
        valid_after: int | None = None,
        valid_before: int | None = None,
    ) -> dict:
        """
        Construye el typed data EIP-712 de USDC `ReceiveWithAuthorization`.

        `intent_id` es el mismo id textual (`pi_...`) que devuelve la API y
        que reciben `submit_authorization` / `submit_authorization_batch`: de
        él se deriva el nonce de la autorización. Nadie tiene que calcular el
        hash on-chain a mano.
        """
        return build_authorization_typed_data(
            payer=payer,
            amount=amount,
            settlement_hub=settlement_hub,
            chain=chain,  # type: ignore[arg-type]
            intent_id=intent_id,
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
        intent_id: str,
        valid_after: int | None = None,
        valid_before: int | None = None,
    ) -> SignedAuthorization:
        """
        Construye y firma un mensaje `ReceiveWithAuthorization`.

        El nonce se deriva del `intent_id` textual (`pi_...`), así que la
        firma solo sirve para pagar ese intent: el nodeit no puede redirigirla.
        """
        return sign_authorization(
            payer=payer,
            amount=amount,
            settlement_hub=settlement_hub,
            chain=chain,  # type: ignore[arg-type]
            private_key=private_key,
            intent_id=intent_id,
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

    def verify(
        self,
        payload: str,
        signature: str,
        secret: str,
        *,
        tolerance: int = DEFAULT_TOLERANCE_SECONDS,
        now: int | None = None,
    ) -> dict:
        """
        Verify a webhook's `X-Signature` header and return the parsed event.
        Call it with the RAW request body.

        The same rules in every CoatiPay SDK (shared vectors in
        `@lacasoft/coatipay-protocol/vectors/webhooks.json`):

        - `t=<seconds>,v1=<hex>` parts, comma-separated (spaces around them are
          ignored). A part without `=` or without a key, a missing or repeated
          `t`, a `t` that is not all digits, or no `v1` → `malformed_header`.
        - `|now - t|` above `tolerance` (300 s) → `timestamp_out_of_tolerance`.
        - Valid if ANY `v1` is the HMAC-SHA256 of `<t>.<body>` with your secret
          (a secret can be rotated without dropping deliveries); otherwise
          `no_matching_signature`.

        Raises `WebhookSignatureError` (a `ValueError`) with the `reason`.
        `now` (seconds) is for tests; by default, the system clock.
        """
        import hashlib
        import hmac
        import json
        import time

        ts: list[str] = []
        firmas: list[str] = []
        for bruta in signature.split(","):
            parte = bruta.strip()
            igual = parte.find("=")
            if igual <= 0:
                raise WebhookSignatureError("malformed_header", "Malformed webhook signature header")
            clave, valor = parte[:igual], parte[igual + 1 :]
            if clave == "t":
                ts.append(valor)
            elif clave == "v1":
                firmas.append(valor)
        # Los mensajes de antes se conservan donde el caso es el mismo.
        if len(ts) == 1 and not (ts[0].isascii() and ts[0].isdigit()):
            raise WebhookSignatureError("malformed_header", "Invalid webhook timestamp")
        if len(ts) != 1 or not firmas:
            raise WebhookSignatureError("malformed_header", "Malformed webhook signature header")

        ahora = int(time.time()) if now is None else now
        if abs(ahora - int(ts[0])) > tolerance:
            raise WebhookSignatureError("timestamp_out_of_tolerance", "Webhook timestamp too old")

        esperada = hmac.new(
            secret.encode(), f"{ts[0]}.{payload}".encode(), hashlib.sha256
        ).hexdigest()
        # En bytes: con dos `str`, compare_digest lanza TypeError si una firma
        # manipulada trae caracteres no ASCII, y el handler fallaría en vez de
        # rechazarla.
        if not any(hmac.compare_digest(esperada.encode(), f.encode()) for f in firmas):
            raise WebhookSignatureError(
                "no_matching_signature", "Webhook signature verification failed"
            )
        return json.loads(payload)

    async def register(self, url: str, events: list[WebhookEventType]) -> dict:
        """Register an endpoint. The returned `secret` signs its deliveries and
        is only returned here: store it."""
        return await _request(
            self._client, "POST", "/webhooks", json={"url": url, "events": events}
        )

    async def rotate_secret(
        self, endpoint_id: str, *, keep_previous_for: int | None = None
    ) -> dict:
        """Rotate an endpoint's signing secret. The new `secret` is only
        returned here: store it. Secret key.

        The previous secret keeps signing next to the new one for
        `keep_previous_for` seconds — 24 h by default, up to 7 days. Meanwhile
        every delivery carries two `v1` signatures and `verify` accepts either,
        so you can change the secret on your server without dropping a
        delivery. With `keep_previous_for=0` the previous secret stops signing
        at once: for one that leaked. Only two secrets ever coexist: rotating
        again within the window retires the oldest.

        Returns `id`, `url`, `events`, `secret` and
        `previous_secret_expires_at` (seconds, or `None` if the previous secret
        no longer signs)."""
        # Sin plazo no se manda cuerpo: lo pone la API.
        cuerpo = (
            {} if keep_previous_for is None else {"json": {"keep_previous_for": keep_previous_for}}
        )
        return await _request(
            self._client,
            "POST",
            f"/webhooks/{quote(endpoint_id, safe='')}/rotate_secret",
            **cuerpo,
        )

    async def list_dead_letters(self, limit: int | None = None) -> dict:
        """Deliveries that exhausted their retries, newest first. Secret key."""
        params = {"limit": limit} if limit is not None else None
        return await _request(self._client, "GET", "/webhooks/dead_letters", params=params)

    async def replay_dead_letter(self, dead_letter_id: str) -> dict:
        """Send a dead letter again: the same event, with the same id, to the
        same endpoint, retries reset. Secret key."""
        return await _request(
            self._client, "POST", f"/webhooks/dead_letters/{dead_letter_id}/replay"
        )
