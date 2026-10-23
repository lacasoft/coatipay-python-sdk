"""Tests for EIP-712 / ERC-3009 authorization helpers."""
import pytest

from coatipay import eip712
from coatipay.eip712 import (
    SignedAuthorization,
    build_authorization_typed_data,
    hash_typed_data,
    intent_id_of,
    intent_ref,
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

# La cartera del comercio del cobro (`merchant_wallet`): entra en el nonce.
MERCHANT = "0x2222222222222222222222222222222222222222"

# Derivaciones esperadas, congeladas a mano en vez de llamar al SDK: si el test
# usara la propia función se compararía consigo misma y no comprobaría nada.
# Salen del paquete del protocolo (TypeScript), que es además lo que calcula el
# hub (ADR-009 §3).
# `keccak256(utf8(id))`: la referencia, y lo que hasta 0.1.x era el nonce.
INTENT_REF = "0x1c398f360a7fffed5f5d87230c4dec29acee4de43d42ebc22983411dcae0e356"
# `keccak256(abi.encode(MERCHANT, INTENT_REF))`: el nonce.
INTENT_ID_NONCE = "0x49b48a490b8527d2af148b118ed2eba075935d53fc90962ecfca1b29378ba541"


class TestBuildAuthorizationTypedData:
    def test_builds_base_sepolia_typed_data(self):
        typed = build_authorization_typed_data(
            payer=PAYER,
            amount=1_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            intent_id=INTENT_ID,
            merchant=MERCHANT,
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
            merchant=MERCHANT,
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
            merchant=MERCHANT,
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
            merchant=MERCHANT,
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
        first = sign_authorization(intent_id=INTENT_ID, merchant=MERCHANT, **common)
        second = sign_authorization(intent_id=OTHER_INTENT_ID, merchant=MERCHANT, **common)

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
                    merchant=MERCHANT,
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
                merchant=MERCHANT,
            )

    def test_no_random_nonce_generator_is_exported(self):
        """
        El generador aleatorio se eliminó en vez de dejarlo obsoleto: seguiría
        produciendo nonces que el contrato rechaza.
        """
        assert not hasattr(eip712, "generate_nonce")


class TestIntentRefYIntentIdOf:
    """
    Los helpers existen para que nadie tenga que calcular el hash a mano: quien
    construye la autorización con su propia wallet necesita exactamente el
    mismo nonce que deriva el SDK, y una derivación distinta produce una firma
    que solo falla al liquidar.
    """

    def test_intent_ref_es_keccak256_del_id_en_utf8(self):
        assert intent_ref(INTENT_ID) == INTENT_REF

    def test_intent_id_of_lleva_la_cartera_del_comercio(self):
        """El mismo cálculo que `SettlementHub.intentIdOf` (ADR-009 §3)."""
        assert intent_id_of(MERCHANT, INTENT_ID) == INTENT_ID_NONCE

    def test_otra_cartera_otro_nonce(self):
        """La firma del pagador fija a quién paga."""
        assert intent_id_of(HUB, INTENT_ID) != INTENT_ID_NONCE

    def test_la_cartera_no_distingue_mayusculas(self):
        assert intent_id_of(MERCHANT.upper().replace("0X", "0x"), INTENT_ID) == INTENT_ID_NONCE

    def test_se_exportan_desde_el_paquete(self):
        """Se exportan desde `coatipay`, no solo desde el submódulo; el viejo
        `intent_id_to_bytes32` ya no, porque daría un nonce que no liquida."""
        import coatipay

        assert coatipay.intent_id_of(MERCHANT, INTENT_ID) == INTENT_ID_NONCE
        assert coatipay.intent_ref(INTENT_ID) == INTENT_REF
        assert "intent_id_of" in coatipay.__all__
        assert not hasattr(coatipay, "intent_id_to_bytes32")

    def test_coincide_con_el_nonce_que_firma_el_sdk(self):
        """La derivación pública y la interna son la misma; si divergieran, el
        integrador que firma a mano quedaría fuera de sincronía con el SDK."""
        auth = sign_authorization(
            payer=PAYER,
            amount=1_000_000,
            settlement_hub=HUB,
            chain="base-sepolia",
            private_key=PRIVATE_KEY,
            intent_id=INTENT_ID,
            merchant=MERCHANT,
        )

        assert auth.nonce == intent_id_of(MERCHANT, INTENT_ID)

    def test_rechaza_un_id_vacio_o_que_no_es_texto(self):
        for bad in ("", "   ", None, 123):
            with pytest.raises(ValueError, match="intent_id is required"):
                intent_ref(bad)  # type: ignore[arg-type]

    def test_rechaza_un_id_que_ya_es_el_bytes32(self):
        with pytest.raises(ValueError, match="looks like the on-chain"):
            intent_ref(INTENT_REF)

    def test_rechaza_una_cartera_ausente_mal_formada_o_cero(self):
        for bad in (None, "", "0x1234", "0x" + "00" * 20):
            with pytest.raises(ValueError, match="merchant"):
                intent_id_of(bad, INTENT_ID)  # type: ignore[arg-type]

    def test_sin_cartera_no_se_puede_firmar(self):
        with pytest.raises(TypeError):
            sign_authorization(
                payer=PAYER,
                amount=1_000_000,
                settlement_hub=HUB,
                chain="base-sepolia",
                private_key=PRIVATE_KEY,
                intent_id=INTENT_ID,
            )
