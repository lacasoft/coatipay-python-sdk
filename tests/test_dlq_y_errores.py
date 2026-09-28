"""Los métodos del DLQ y la clase de los errores que devuelve la API."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from coatipay import AuthError, CoatiPay, CoatiPaySDKError, RateLimitError

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
