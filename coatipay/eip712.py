"""EIP-712 / ERC-3009 helpers for gasless USDC settlement on Base."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal

from eth_keys import keys
from eth_utils import keccak, to_hex, to_bytes


SupportedChain = Literal["base", "base-sepolia"]

USDC_ADDRESSES: dict[SupportedChain, str] = {
    "base": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "base-sepolia": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
}

CHAIN_IDS: dict[SupportedChain, int] = {
    "base": 8453,
    "base-sepolia": 84532,
}

USDC_DOMAIN_NAMES: dict[SupportedChain, str] = {
    "base": "USD Coin",
    "base-sepolia": "USDC",
}

USDC_DOMAIN_VERSION = "2"
DEFAULT_VALIDITY_WINDOW_SECONDS = 30 * 60

EIP712DOMAIN_TYPEHASH = keccak(
    b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)

RECEIVE_WITH_AUTHORIZATION_TYPEHASH = keccak(
    b"ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
)


@dataclass
class SignedAuthorization:
    """
    Autorización ERC-3009 ReceiveWithAuthorization ya firmada, lista para enviar.

    `nonce` **es el identificador on-chain del intent** (`intent_id`), no un
    valor aleatorio: el contrato exige esa igualdad para que la firma del
    pagador no pueda aplicarse a otro intent.
    """

    payer: str
    valid_after: int
    valid_before: int
    nonce: str
    signature: str


def _is_address(value: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", value))


def _normalize_address(value: str) -> str:
    if not _is_address(value):
        raise ValueError(f"Invalid address: {value}")
    return value.lower()


def _encode_uint256(value: int) -> bytes:
    return value.to_bytes(32, "big")


def _encode_address(value: str) -> bytes:
    return bytes.fromhex(_normalize_address(value)[2:]).rjust(32, b"\x00")


def _encode_bytes32(value: str) -> bytes:
    if isinstance(value, str):
        if value.startswith("0x"):
            value = value[2:]
        return bytes.fromhex(value.zfill(64))
    return bytes(value).ljust(32, b"\x00")


def _encode_abi(types: list[str], values: list) -> bytes:
    parts: list[bytes] = []
    for t, v in zip(types, values):
        if t == "bytes32":
            parts.append(_encode_bytes32(v))
        elif t == "uint256":
            parts.append(_encode_uint256(v))
        elif t == "address":
            parts.append(_encode_address(v))
        else:
            raise ValueError(f"Unsupported ABI type: {t}")
    return b"".join(parts)


def _validate_intent_id(value: str) -> str:
    """
    Comprueba que el intent llega como bytes32 (`0x` + 64 hex).

    En JavaScript el tipo `Hex` y el typecheck atrapan un intent mal formado
    antes de ejecutar; aquí no hay compilador, así que se valida en tiempo de
    ejecución. Sirve sobre todo para distinguirlo del id de la API (`pi_...`),
    que es otra cosa: el contrato compara contra el identificador on-chain.
    """
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
        raise ValueError(
            f"Invalid intent_id: {value!r} "
            "(expected the on-chain intent id, 32-byte hex: 0x + 64 chars)"
        )
    return value


def build_authorization_typed_data(
    payer: str,
    amount: int,
    settlement_hub: str,
    chain: SupportedChain,
    *,
    intent_id: str,
    valid_after: int | None = None,
    valid_before: int | None = None,
) -> dict:
    """
    Construye el typed data EIP-712 de USDC `ReceiveWithAuthorization`.

    `intent_id` es el identificador **on-chain** del intent que se paga
    (bytes32), y es obligatorio: de él sale el nonce de la autorización. El
    contrato exige esa atadura porque quien envía la transacción —el nodeit,
    la parte no confiable— podía, con un nonce aleatorio, aplicar la firma
    del pagador a otro intent y quedarse el pago.

    El campo del mensaje se sigue llamando `nonce`: lo fija ERC-3009. Lo que
    cambia es de dónde sale su valor.
    """
    now_seconds = int(time.time())
    valid_after = valid_after if valid_after is not None else 0
    valid_before = valid_before if valid_before is not None else now_seconds + DEFAULT_VALIDITY_WINDOW_SECONDS
    # El nonce ES el intent: así la firma solo sirve para pagar ese intent.
    nonce = _validate_intent_id(intent_id)

    return {
        "domain": {
            "name": USDC_DOMAIN_NAMES[chain],
            "version": USDC_DOMAIN_VERSION,
            "chainId": CHAIN_IDS[chain],
            "verifyingContract": USDC_ADDRESSES[chain],
        },
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "ReceiveWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "primaryType": "ReceiveWithAuthorization",
        "message": {
            "from": _normalize_address(payer),
            "to": _normalize_address(settlement_hub),
            "value": amount,
            "validAfter": valid_after,
            "validBefore": valid_before,
            "nonce": nonce,
        },
    }


def hash_typed_data(typed_data: dict) -> str:
    """Compute the EIP-712 digest for the given typed data."""
    domain = typed_data["domain"]
    message = typed_data["message"]

    domain_separator = keccak(
        _encode_abi(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [
                EIP712DOMAIN_TYPEHASH,
                keccak(domain["name"].encode("utf-8")),
                keccak(domain["version"].encode("utf-8")),
                domain["chainId"],
                domain["verifyingContract"],
            ],
        )
    )

    struct_hash = keccak(
        _encode_abi(
            ["bytes32", "address", "address", "uint256", "uint256", "uint256", "bytes32"],
            [
                RECEIVE_WITH_AUTHORIZATION_TYPEHASH,
                message["from"],
                message["to"],
                message["value"],
                message["validAfter"],
                message["validBefore"],
                message["nonce"],
            ],
        )
    )

    digest = keccak(b"\x19\x01" + domain_separator + struct_hash)
    return to_hex(digest)


def sign_authorization(
    payer: str,
    amount: int,
    settlement_hub: str,
    chain: SupportedChain,
    private_key: str,
    *,
    intent_id: str,
    valid_after: int | None = None,
    valid_before: int | None = None,
) -> SignedAuthorization:
    """
    Construye y firma un mensaje `ReceiveWithAuthorization`.

    `intent_id` (bytes32 on-chain) es obligatorio: la firma queda atada a ese
    intent y solo a ese, para que el nodeit no pueda redirigir el cobro.
    """
    typed_data = build_authorization_typed_data(
        payer=payer,
        amount=amount,
        settlement_hub=settlement_hub,
        chain=chain,
        intent_id=intent_id,
        valid_after=valid_after,
        valid_before=valid_before,
    )
    digest = hash_typed_data(typed_data)

    if isinstance(private_key, str) and private_key.startswith("0x"):
        private_key = private_key[2:]

    pk = keys.PrivateKey(to_bytes(hexstr=private_key))
    signed = pk.sign_msg_hash(to_bytes(hexstr=digest))

    # Normalize v to 27/28 to match Ethereum convention used by the JS SDK.
    v = signed.v
    if v < 27:
        v += 27
    signature_bytes = signed.r.to_bytes(32, "big") + signed.s.to_bytes(32, "big") + bytes([v])

    return SignedAuthorization(
        payer=typed_data["message"]["from"],
        valid_after=typed_data["message"]["validAfter"],
        valid_before=typed_data["message"]["validBefore"],
        nonce=typed_data["message"]["nonce"],
        signature=to_hex(signature_bytes),
    )


def split_signature(signature: str) -> dict:
    """Split a 65-byte hex signature into {v, r, s}."""
    sig_bytes = to_bytes(hexstr=signature)
    if len(sig_bytes) != 65:
        raise ValueError(f"Invalid signature length: {len(sig_bytes)} bytes (expected 65)")

    r = to_hex(sig_bytes[:32])
    s = to_hex(sig_bytes[32:64])
    v = sig_bytes[64]
    if v < 27:
        v += 27
    return {"v": v, "r": r, "s": s}


def serialize_authorization(auth: SignedAuthorization) -> dict:
    """Convert a SignedAuthorization to the wire format expected by the API."""
    return {
        "payer": auth.payer,
        "valid_after": str(auth.valid_after),
        "valid_before": str(auth.valid_before),
        "nonce": auth.nonce,
        "signature": auth.signature,
    }
