"""Tests for EIP-712 / ERC-3009 authorization helpers."""
import pytest

from coatipay.eip712 import (
    SignedAuthorization,
    build_authorization_typed_data,
    generate_nonce,
    hash_typed_data,
    serialize_authorization,
    sign_authorization,
    split_signature,
)


class TestBuildAuthorizationTypedData:
    def test_builds_base_sepolia_typed_data(self):
        typed = build_authorization_typed_data(
            payer="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            amount=1_000_000,
            settlement_hub="0xe2D6EaF23c285E827f37dC5Ec05fFfD860dBE0e1",
            chain="base-sepolia",
            nonce="0x" + "00" * 32,
            valid_after=0,
            valid_before=2_000_000_000,
        )

        assert typed["domain"]["name"] == "USDC"
        assert typed["domain"]["version"] == "2"
        assert typed["domain"]["chainId"] == 84532
        assert typed["domain"]["verifyingContract"] == "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
        assert typed["primaryType"] == "ReceiveWithAuthorization"

        msg = typed["message"]
        assert msg["from"] == "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert msg["to"] == "0xe2d6eaf23c285e827f37dc5ec05fffd860dbe0e1"
        assert msg["value"] == 1_000_000
        assert msg["validAfter"] == 0
        assert msg["validBefore"] == 2_000_000_000
        assert msg["nonce"] == "0x" + "00" * 32

    def test_defaults_validity_window_and_nonce(self):
        typed = build_authorization_typed_data(
            payer="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            amount=1_000_000,
            settlement_hub="0xe2D6EaF23c285E827f37dC5Ec05fFfD860dBE0e1",
            chain="base",
        )

        assert typed["domain"]["chainId"] == 8453
        assert typed["domain"]["name"] == "USD Coin"
        assert typed["message"]["validAfter"] == 0
        assert typed["message"]["validBefore"] > 0
        assert typed["message"]["nonce"].startswith("0x")
        assert len(typed["message"]["nonce"]) == 66


class TestSignAuthorization:
    def test_signs_with_private_key(self):
        private_key = "0x" + "11" * 32
        auth = sign_authorization(
            payer="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            amount=1_000_000,
            settlement_hub="0xe2D6EaF23c285E827f37dC5Ec05fFfD860dBE0e1",
            chain="base-sepolia",
            private_key=private_key,
            nonce="0x" + "00" * 32,
            valid_after=0,
            valid_before=2_000_000_000,
        )

        assert isinstance(auth, SignedAuthorization)
        assert auth.payer == "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert auth.valid_after == 0
        assert auth.valid_before == 2_000_000_000
        assert auth.nonce == "0x" + "00" * 32
        assert auth.signature.startswith("0x")
        assert len(auth.signature) == 132  # 65 bytes * 2 + 2

    def test_signature_matches_js_sdk_reference(self):
        """Cross-language sanity check: same inputs produce the same signature."""
        private_key = "0x" + "11" * 32
        auth = sign_authorization(
            payer="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            amount=1_000_000,
            settlement_hub="0xe2D6EaF23c285E827f37dC5Ec05fFfD860dBE0e1",
            chain="base-sepolia",
            private_key=private_key,
            nonce="0x" + "00" * 32,
            valid_after=0,
            valid_before=2_000_000_000,
        )

        expected_signature = (
            "0xedeb072b543902cff56f05d171f505c7bda129cf61c4b94f5905709c822c255e"
            "49994f31bdb8946811cdb9125c22a87456969d4c847243f0b538fd381483678c1c"
        )
        assert auth.signature == expected_signature


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
            payer="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            valid_after=0,
            valid_before=2_000_000_000,
            nonce="0x" + "00" * 32,
            signature="0x" + "11" * 65,
        )
        serialized = serialize_authorization(auth)

        assert serialized["payer"] == auth.payer
        assert serialized["valid_after"] == "0"
        assert serialized["valid_before"] == "2000000000"
        assert serialized["nonce"] == auth.nonce
        assert serialized["signature"] == auth.signature


class TestGenerateNonce:
    def test_generates_32_byte_hex(self):
        nonce = generate_nonce()
        assert nonce.startswith("0x")
        assert len(nonce) == 66

    def test_generates_unique_nonces(self):
        assert generate_nonce() != generate_nonce()


class TestHashTypedData:
    def test_digest_starts_with_eip712_prefix(self):
        typed = build_authorization_typed_data(
            payer="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            amount=1_000_000,
            settlement_hub="0xe2D6EaF23c285E827f37dC5Ec05fFfD860dBE0e1",
            chain="base-sepolia",
        )
        digest = hash_typed_data(typed)
        assert digest.startswith("0x")
        assert len(digest) == 66
