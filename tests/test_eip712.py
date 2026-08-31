"""Tests for EIP-712 / ERC-3009 authorization helpers."""
import pytest

from coatipay import eip712
from coatipay.eip712 import (
    SignedAuthorization,
    build_authorization_typed_data,
    hash_typed_data,
    intent_id_to_bytes32,
    serialize_authorization,
    sign_authorization,
    split_signature,
)

PAYER = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
HUB = "0xe2D6EaF23c285E827f37dC5Ec05fFfD860dBE0e1"
PRIVATE_KEY = "0x" + "11" * 32

# Ids de intent tal y como los devuelve la API: texto, no bytes32. Se firma
# atado a uno de estos: el nonce de la autorización no es un valor libre, es el
# intent que se paga.
INTENT_ID = "pi_abc123"
OTHER_INTENT_ID = "pi_def456"

# Derivación esperada (`keccak256(utf8(id))`), congelada a mano en vez de
# llamar al SDK: si el test usara la propia función se compararía consigo misma
# y no comprobaría nada. Es además el valor que produce el SDK de JavaScript.
INTENT_ID_NONCE = "0x1c398f360a7fffed5f5d87230c4dec29acee4de43d42ebc22983411dcae0e356"


class TestBuildAuthorizationTypedData:
    def test_builds_base_sepolia_typed_data(self):
        typed = build_authorization_typed_data(
            payer=PAYER,
            amount=1_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            intent_id=INTENT_ID,
            valid_after=0,
            valid_before=2_000_000_000,
        )

        assert typed["domain"]["name"] == "USDC"
        assert typed["domain"]["version"] == "2"
        assert typed["domain"]["chainId"] == 84532
        assert typed["domain"]["verifyingContract"] == "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
        assert typed["primaryType"] == "ReceiveWithAuthorization"

        msg = typed["message"]
        assert msg["from"] == PAYER
        assert msg["to"] == "0xe2d6eaf23c285e827f37dc5ec05fffd860dbe0e1"
        assert msg["value"] == 1_000_000
        assert msg["validAfter"] == 0
        assert msg["validBefore"] == 2_000_000_000
        # El campo se sigue llamando `nonce` (lo fija ERC-3009), pero su valor
        # es el intent.
        assert msg["nonce"] == INTENT_ID_NONCE

    def test_defaults_validity_window(self):
        typed = build_authorization_typed_data(
            payer=PAYER,
            amount=1_000_000,
            settlement_hub=HUB,
            chain="base",
            intent_id=INTENT_ID,
        )

        assert typed["domain"]["chainId"] == 8453
        assert typed["domain"]["name"] == "USD Coin"
        assert typed["message"]["validAfter"] == 0
        assert typed["message"]["validBefore"] > 0


class TestNonceBoundToIntent:
    """
    La atadura nonce == intent_id es la defensa: sin ella, el nodeit —que es
    quien envía la transacción, y la parte no confiable— podía aplicar la firma
    del pagador a OTRO intent y quedarse el pago.
    """

    def test_nonce_is_the_derivation_of_the_textual_intent_id(self):
        typed = build_authorization_typed_data(
            payer=PAYER,
            amount=5_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            intent_id=INTENT_ID,
        )

        assert typed["message"]["nonce"] == INTENT_ID_NONCE

    def test_signed_authorization_carries_the_derived_intent_id_as_nonce(self):
        auth = sign_authorization(
            payer=PAYER,
            amount=5_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            private_key=PRIVATE_KEY,
            intent_id=INTENT_ID,
        )

        assert auth.nonce == INTENT_ID_NONCE

    def test_different_intents_produce_different_signatures(self):
        """Dos intents distintos no comparten firma: no hay firma reutilizable."""
        common = {
            "payer": PAYER,
            "amount": 5_000_000,
            "settlement_hub": HUB,
            "chain": "base-sepolia",
            "private_key": PRIVATE_KEY,
            "valid_after": 0,
            "valid_before": 2_000_000_000,
        }
        first = sign_authorization(intent_id=INTENT_ID, **common)
        second = sign_authorization(intent_id=OTHER_INTENT_ID, **common)

        assert first.nonce != second.nonce
        assert first.signature != second.signature

    def test_intent_id_is_required(self):
        """
        Sin `intent_id` no se puede firmar. En JavaScript esto lo atrapa el
        typecheck; en Python el fallo tiene que ser en tiempo de ejecución, y
        es preferible aquí que al liquidar.
        """
        with pytest.raises(TypeError):
            build_authorization_typed_data(
                payer=PAYER,
                amount=1_000_000,
                settlement_hub=HUB,
                chain="base-sepolia",
            )
        with pytest.raises(TypeError):
            sign_authorization(
                payer=PAYER,
                amount=1_000_000,
                settlement_hub=HUB,
                chain="base-sepolia",
                private_key=PRIVATE_KEY,
            )

    def test_rejects_an_empty_intent_id(self):
        """
        Un id vacío no es un intent: firmaría atado a `keccak256("")`, un nonce
        con la forma correcta y sin intent detrás.
        """
        for empty in ("", "   "):
            with pytest.raises(ValueError, match="intent_id is required"):
                build_authorization_typed_data(
                    payer=PAYER,
                    amount=1_000_000,
                    settlement_hub=HUB,
                    chain="base-sepolia",
                    intent_id=empty,
                )

    def test_rejects_an_intent_id_that_is_already_the_bytes32(self):
        """
        Único error de forma que el SDK sabe reconocer: pasar el id ya
        hasheado. Se volvería a hashear y saldría un nonce plausible pero
        equivocado, que solo daría la cara al liquidar.
        """
        with pytest.raises(ValueError, match="looks like the on-chain"):
            build_authorization_typed_data(
                payer=PAYER,
                amount=1_000_000,
                settlement_hub=HUB,
                chain="base-sepolia",
                intent_id=INTENT_ID_NONCE,
            )

    def test_no_random_nonce_generator_is_exported(self):
        """
        El generador aleatorio se eliminó en vez de dejarlo obsoleto: seguiría
        produciendo nonces que el contrato rechaza.
        """
        assert not hasattr(eip712, "generate_nonce")


class TestIntentIdToBytes32:
    """
    El helper existe para que nadie tenga que calcular el hash a mano: quien
    construye la autorización con su propia wallet necesita exactamente el
    mismo nonce que deriva el SDK, y una derivación distinta produce una firma
    atada a un intent inexistente que solo falla al liquidar.
    """

    def test_derives_keccak256_of_the_utf8_id(self):
        assert intent_id_to_bytes32(INTENT_ID) == INTENT_ID_NONCE

    def test_is_exported_from_the_package(self):
        """Se exporta desde `coatipay`, no solo desde el submódulo."""
        import coatipay

        assert coatipay.intent_id_to_bytes32(INTENT_ID) == INTENT_ID_NONCE
        assert "intent_id_to_bytes32" in coatipay.__all__

    def test_matches_the_nonce_the_sdk_signs(self):
        """La derivación pública y la interna son la misma; si divergieran, el
        integrador que firma a mano quedaría fuera de sincronía con el SDK."""
        auth = sign_authorization(
            payer=PAYER,
            amount=1_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            private_key=PRIVATE_KEY,
            intent_id=INTENT_ID,
        )

        assert auth.nonce == intent_id_to_bytes32(INTENT_ID)

    def test_rejects_empty_or_non_string(self):
        for bad in ("", "   ", None, 123):
            with pytest.raises(ValueError, match="intent_id is required"):
                intent_id_to_bytes32(bad)  # type: ignore[arg-type]

    def test_rejects_an_id_that_is_already_the_bytes32(self):
        with pytest.raises(ValueError, match="looks like the on-chain"):
            intent_id_to_bytes32(INTENT_ID_NONCE)


class TestSignAuthorization:
    def test_signs_with_private_key(self):
        auth = sign_authorization(
            payer=PAYER,
            amount=1_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            private_key=PRIVATE_KEY,
            intent_id=INTENT_ID,
            valid_after=0,
            valid_before=2_000_000_000,
        )

        assert isinstance(auth, SignedAuthorization)
        assert auth.payer == PAYER
        assert auth.valid_after == 0
        assert auth.valid_before == 2_000_000_000
        assert auth.nonce == INTENT_ID_NONCE
        assert auth.signature.startswith("0x")
        assert len(auth.signature) == 132  # 65 bytes * 2 + 2

    def test_signature_matches_js_sdk_reference(self):
        """Cross-language sanity check: same inputs produce the same signature."""
        auth = sign_authorization(
            payer=PAYER,
            amount=1_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            private_key=PRIVATE_KEY,
            intent_id=INTENT_ID,
            valid_after=0,
            valid_before=2_000_000_000,
        )

        # Valor congelado ejecutando `signReceiveAuthorization` del SDK de
        # JavaScript con estos mismos parámetros (mismo id textual: la
        # derivación a bytes32 ocurre dentro de cada SDK).
        expected_signature = (
            "0xbaa94b8c00d397cd8eb1a102b00a269d6089618561ca6aa6bd5f64ccd6d5489b"
            "4bcf8ce7bb5592c577f6b357155b2ac5c71de69af0a59524870aefd0824f529b1c"
        )
        assert auth.signature == expected_signature
        # Y el nonce que ambos derivan del mismo id textual también coincide.
        assert auth.nonce == INTENT_ID_NONCE


class TestSplitSignature:
    def test_splits_65_byte_signature(self):
        sig = "0x" + "11" * 32 + "22" * 32 + "1c"
        parts = split_signature(sig)

        assert parts["v"] == 28
        assert parts["r"] == "0x" + "11" * 32
        assert parts["s"] == "0x" + "22" * 32

    def test_normalizes_low_v(self):
        sig = "0x" + "11" * 32 + "22" * 32 + "00"
        parts = split_signature(sig)

        assert parts["v"] == 27

    def test_rejects_wrong_length(self):
        with pytest.raises(ValueError, match="Invalid signature length"):
            split_signature("0x1122")


class TestSerializeAuthorization:
    def test_serializes_to_wire_format(self):
        auth = SignedAuthorization(
            payer=PAYER,
            valid_after=0,
            valid_before=2_000_000_000,
            nonce=INTENT_ID_NONCE,
            signature="0x" + "11" * 65,
        )
        serialized = serialize_authorization(auth)

        assert serialized["payer"] == auth.payer
        assert serialized["valid_after"] == "0"
        assert serialized["valid_before"] == "2000000000"
        # El nonce viaja tal cual: el nodeit no puede cambiarlo sin invalidar
        # la firma, y el contrato lo compara con el intent que liquida.
        assert serialized["nonce"] == INTENT_ID_NONCE
        assert serialized["signature"] == auth.signature


class TestHashTypedData:
    def test_digest_starts_with_eip712_prefix(self):
        typed = build_authorization_typed_data(
            payer=PAYER,
            amount=1_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            intent_id=INTENT_ID,
        )
        digest = hash_typed_data(typed)
        assert digest.startswith("0x")
        assert len(digest) == 66
