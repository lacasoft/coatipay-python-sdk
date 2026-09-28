"""
Vectores compartidos entre los SDK de CoatiPay (JS, Python, PHP).

El mismo juego de casos que pasan los otros SDK, publicado en
`@lacasoft/coatipay-protocol` (`vectors/`). `tests/vectors/` es una copia: el CI
comprueba que es la de la última versión publicada. Si este SDK se desvía,
falla aquí y no en producción.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import coatipay.errors as errores_sdk
from coatipay.eip712 import (
    build_authorization_typed_data,
    hash_typed_data,
    intent_id_to_bytes32,
    serialize_authorization,
    sign_authorization,
)
from coatipay.resources import Webhooks

DIRECTORIO = Path(os.environ.get("COATIPAY_VECTORES", Path(__file__).parent / "vectors"))


def vector(nombre: str) -> dict:
    return json.loads((DIRECTORIO / nombre).read_text(encoding="utf-8"))


# ── nonce ──────────────────────────────────────────────────────────

NONCE = vector("nonce.json")


@pytest.mark.parametrize("caso", NONCE["casos"], ids=lambda c: repr(c["intent_id"]))
def test_nonce(caso):
    assert intent_id_to_bytes32(caso["intent_id"]) == caso["nonce"]


@pytest.mark.parametrize("caso", NONCE["rechazados"], ids=lambda c: c["motivo"])
def test_nonce_rechazado(caso):
    with pytest.raises(ValueError):
        intent_id_to_bytes32(caso["intent_id"])


# ── autorización ERC-3009 ──────────────────────────────────────────

AUTORIZACION = vector("autorizacion.json")


def _params(caso: dict) -> dict:
    e = caso["entrada"]
    return {
        "payer": caso["esperado"]["api_body"]["payer"],
        "amount": int(e["amount"]),
        "settlement_hub": e["settlement_hub"],
        "chain": e["chain"],
        "intent_id": e["intent_id"],
        "valid_after": int(e["valid_after"]),
        "valid_before": int(e["valid_before"]),
    }


def _sin_mayusculas(d: dict, campos: tuple[str, ...]) -> dict:
    """Las direcciones, sin distinguir mayúsculas: el checksum EIP-55 es
    presentación (se firma sobre los bytes). Este SDK las da en minúsculas."""
    return {k: (v.lower() if k in campos else v) for k, v in d.items()}


def _id(caso: dict) -> str:
    return f"{caso['entrada']['chain']}-{caso['entrada']['intent_id']}"


@pytest.mark.parametrize("caso", AUTORIZACION["casos"], ids=_id)
def test_autorizacion_dominio_mensaje_y_digest(caso):
    e = caso["esperado"]
    tipado = build_authorization_typed_data(**_params(caso))
    assert tipado["domain"] == e["domain"]
    mensaje = {
        **tipado["message"],
        "value": str(tipado["message"]["value"]),
        "validAfter": str(tipado["message"]["validAfter"]),
        "validBefore": str(tipado["message"]["validBefore"]),
    }
    campos = ("from", "to")
    assert _sin_mayusculas(mensaje, campos) == _sin_mayusculas(e["message"], campos)
    assert hash_typed_data(tipado) == e["digest"]


@pytest.mark.parametrize("caso", AUTORIZACION["casos"], ids=_id)
def test_autorizacion_firma_y_cuerpo_de_la_api(caso):
    e = caso["esperado"]
    firmada = sign_authorization(
        private_key=caso["entrada"]["payer_private_key"], **_params(caso)
    )
    assert firmada.signature == e["signature"]
    assert _sin_mayusculas(serialize_authorization(firmada), ("payer",)) == _sin_mayusculas(
        e["api_body"], ("payer",)
    )


# ── webhooks ───────────────────────────────────────────────────────

WEBHOOKS = vector("webhooks.json")


@pytest.mark.parametrize("caso", WEBHOOKS["casos"], ids=lambda c: c["nombre"])
def test_webhook(caso):
    webhooks = Webhooks(client=None)  # verificar no llama a la API
    kwargs = {"now": WEBHOOKS["ahora"]}
    if "tolerancia" in caso:
        kwargs["tolerance"] = caso["tolerancia"]
    cuerpo = caso.get("cuerpo", WEBHOOKS["cuerpo"])

    def verificar():
        return webhooks.verify(cuerpo, caso["cabecera"], WEBHOOKS["secreto"], **kwargs)

    if caso["esperado"]["valida"]:
        evento = verificar()
        if "cuerpo" not in caso:
            assert evento == WEBHOOKS["evento"]
    else:
        with pytest.raises(errores_sdk.WebhookSignatureError) as info:
            verificar()
        assert info.value.reason == caso["esperado"]["motivo"]


# ── errores ────────────────────────────────────────────────────────

ERRORES = vector("errores.json")


def _clase(code: str) -> errores_sdk.CoatiPaySDKError:
    return errores_sdk.classify_error(
        code=code, message="m", param=None, doc_url="https://coatipay.com/docs"
    )


@pytest.mark.parametrize("code", sorted(ERRORES["codigos"]))
def test_error_de_cada_codigo(code):
    e = _clase(code)
    assert type(e).__name__ == ERRORES["codigos"][code]["clase"]
    assert isinstance(e, errores_sdk.CoatiPaySDKError)


def test_error_desconocido_es_la_clase_base():
    assert type(_clase(ERRORES["desconocido"]["code"])).__name__ == ERRORES["desconocido"]["clase"]
