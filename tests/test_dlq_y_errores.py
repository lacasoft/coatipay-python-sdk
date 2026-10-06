"""Los métodos del DLQ y la clase de los errores que devuelve la API."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from coatipay import AuthError, CoatiPay, CoatiPaySDKError, NetworkError, RateLimitError

ENTREGA = {
    "id": "dlq_1",
    "endpoint_id": "we_1",
    "endpoint_url": "https://example.com/hook",
    "event_id": "evt_1",
    "event_type": "payment_intent.settled",
    "delivery_id": "whd_1",
    "attempts": 6,
    "last_error": "HTTP 500",
    "last_attempted_at": 1_790_000_000,
    "created_at": 1_790_000_000,
    "replayed_at": None,
    "payload": {"id": "evt_1"},
}


async def test_list_dead_letters_pide_get_con_el_limite():
    respuesta = httpx.Response(200, json={"data": [ENTREGA], "has_more": False})
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=respuesta) as req:
        r = await CoatiPay(api_key="sk_live_test").webhooks.list_dead_letters(limit=5)
    args, kwargs = req.call_args
    assert args == ("GET", "/v1/webhooks/dead_letters")
    assert kwargs["params"] == {"limit": 5}
    assert r["data"][0]["delivery_id"] == "whd_1"


async def test_replay_dead_letter_pide_post():
    respuesta = httpx.Response(202, json={**ENTREGA, "replayed_at": 1_790_000_100})
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=respuesta) as req:
        r = await CoatiPay(api_key="sk_live_test").webhooks.replay_dead_letter("dlq_1")
    args, _ = req.call_args
    assert args == ("POST", "/v1/webhooks/dead_letters/dlq_1/replay")
    assert r["replayed_at"] == 1_790_000_100


ROTADO = {
    "id": "we_1",
    "url": "https://example.com/hook",
    "events": ["payment_intent.settled"],
    "secret": "whsec_nuevo",
    "previous_secret_expires_at": 1_790_086_400,
}


async def test_rotate_secret_pide_post_sin_cuerpo_el_plazo_lo_pone_la_api():
    respuesta = httpx.Response(200, json=ROTADO)
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=respuesta) as req:
        r = await CoatiPay(api_key="sk_live_test").webhooks.rotate_secret("we_1")
    args, kwargs = req.call_args
    assert args == ("POST", "/v1/webhooks/we_1/rotate_secret")
    assert kwargs == {}
    assert r == ROTADO


@pytest.mark.parametrize("plazo", [0, 3600])
async def test_rotate_secret_manda_keep_previous_for_tambien_cuando_es_cero(plazo):
    respuesta = httpx.Response(200, json={**ROTADO, "previous_secret_expires_at": None})
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=respuesta) as req:
        r = await CoatiPay(api_key="sk_live_test").webhooks.rotate_secret(
            "we_1", keep_previous_for=plazo
        )
    _, kwargs = req.call_args
    assert kwargs == {"json": {"keep_previous_for": plazo}}
    assert r["previous_secret_expires_at"] is None


async def test_rotate_secret_escapa_el_id_en_la_ruta():
    respuesta = httpx.Response(200, json=ROTADO)
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=respuesta) as req:
        await CoatiPay(api_key="sk_live_test").webhooks.rotate_secret("we_1/../otra")
    args, _ = req.call_args
    assert args == ("POST", "/v1/webhooks/we_1%2F..%2Fotra/rotate_secret")


def test_durante_la_ventana_verify_acepta_el_secreto_nuevo_y_el_anterior():
    import hashlib
    import hmac
    import json
    import time

    from coatipay import WebhookSignatureError

    payload = json.dumps({"id": "evt_r", "type": "payment_intent.settled", "data": {}})
    t = int(time.time())

    def firma(secreto: str) -> str:
        return hmac.new(secreto.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()

    # Como la manda la API tras rotar: primero la del nuevo, después la del anterior.
    cabecera = f"t={t},v1={firma('whsec_nuevo')},v1={firma('whsec_anterior')}"
    webhooks = CoatiPay(api_key="sk_live_test").webhooks
    assert webhooks.verify(payload, cabecera, "whsec_nuevo")["id"] == "evt_r"
    assert webhooks.verify(payload, cabecera, "whsec_anterior")["id"] == "evt_r"
    with pytest.raises(WebhookSignatureError) as info:
        webhooks.verify(payload, cabecera, "whsec_otro")
    assert info.value.reason == "no_matching_signature"


async def _peticion_que_sale(llamada) -> httpx.Request:
    """La petición tal como la arma el cliente del SDK, con sus cabeceras por
    defecto: lo que de verdad llega a la API. Simular `request` no lo enseña."""
    salieron: list[httpx.Request] = []

    async def send(self, request, **kwargs):
        salieron.append(request)
        return httpx.Response(200, json={}, request=request)

    with patch.object(httpx.AsyncClient, "send", new=send):
        await llamada(CoatiPay(api_key="sk_live_test"))
    return salieron[0]


@pytest.mark.parametrize(
    "llamada",
    [
        lambda relay: relay.payment_intents.cancel("pi_1"),
        lambda relay: relay.webhooks.replay_dead_letter("dlq_1"),
        lambda relay: relay.webhooks.rotate_secret("we_1"),
    ],
    ids=["cancel", "replay_dead_letter", "rotate_secret"],
)
async def test_un_post_sin_cuerpo_no_declara_json(llamada):
    # La API rechaza con 400 un POST que declara JSON y llega vacío.
    peticion = await _peticion_que_sale(llamada)
    assert peticion.method == "POST"
    assert peticion.content == b""
    assert "content-type" not in peticion.headers
    assert peticion.headers["authorization"] == "Bearer sk_live_test"


@pytest.mark.parametrize(
    "llamada",
    [
        lambda relay: relay.webhooks.register("https://example.com/h", ["payment_intent.settled"]),
        lambda relay: relay.webhooks.rotate_secret("we_1", keep_previous_for=0),
    ],
    ids=["register", "rotate_secret con plazo"],
)
async def test_un_post_con_cuerpo_si_declara_json(llamada):
    peticion = await _peticion_que_sale(llamada)
    assert peticion.headers["content-type"] == "application/json"
    assert peticion.content != b""


def _error(status: int, code: str, doc_url: str | None = None) -> httpx.Response:
    error = {"code": code, "message": "m", "param": None}
    if doc_url is not None:
        error["doc_url"] = doc_url
    return httpx.Response(status, json={"error": error})


@pytest.mark.parametrize(
    ("status", "code", "clase"),
    [(401, "invalid_api_key", AuthError), (429, "rate_limited", RateLimitError)],
)
async def test_un_error_de_la_api_llega_con_su_clase(status, code, clase):
    respuesta = _error(status, code, f"https://coatipay.com/docs/errors/{code}")
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=respuesta):
        with pytest.raises(clase) as info:
            await CoatiPay(api_key="sk_live_test").payment_intents.retrieve("pi_x")
    assert isinstance(info.value, CoatiPaySDKError)
    assert info.value.code == code


async def test_sin_doc_url_apunta_a_la_pagina_real_del_codigo():
    # Antes era https://docs.coatipay.com, que no existe.
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=_error(404, "intent_not_found")):
        with pytest.raises(CoatiPaySDKError) as info:
            await CoatiPay(api_key="sk_live_test").payment_intents.retrieve("pi_x")
    assert info.value.doc_url == "https://coatipay.com/docs/errors/intent_not_found"


async def test_create_con_idempotency_key_la_manda_en_la_cabecera():
    respuesta = httpx.Response(201, json={"id": "pi_1", "status": "created"})
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=respuesta) as req:
        await CoatiPay(api_key="sk_live_test").payment_intents.create(
            amount=1_000_000, currency="usdc", chain="base", idempotency_key="order_123"
        )
    _, kwargs = req.call_args
    assert kwargs["headers"] == {"Idempotency-Key": "order_123"}
    assert "idempotency_key" not in kwargs["json"]


async def test_create_sin_idempotency_key_no_manda_cabecera():
    respuesta = httpx.Response(201, json={"id": "pi_1", "status": "created"})
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=respuesta) as req:
        await CoatiPay(api_key="sk_live_test").payment_intents.create(amount=1_000_000, currency="usdc", chain="base")
    _, kwargs = req.call_args
    assert "headers" not in kwargs


async def test_timeout_es_network_error_sin_status():
    with patch.object(
        httpx.AsyncClient, "request", new_callable=AsyncMock, side_effect=httpx.ReadTimeout("lento")
    ):
        with pytest.raises(NetworkError) as info:
            await CoatiPay(api_key="sk_live_test").payment_intents.retrieve("pi_1")
    assert info.value.status is None
    assert "timed out" in str(info.value)
    assert isinstance(info.value.__cause__, httpx.ReadTimeout)
