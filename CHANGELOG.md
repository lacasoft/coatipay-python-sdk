# Changelog

## 0.1.3 — 2026-09-28

### Fixed

- **`webhooks.verify` no longer crashes on a malformed `X-Signature` header.**
  A part without `=` raised `IndexError`; now it is rejected like any other bad
  header. A tampered `v1` with non-ASCII characters no longer raises
  `TypeError` either.
- **`webhooks.verify` accepts a secret rotation**: the request is valid if
  **any** `v1` matches. It used to check only the last one.
- **`doc_url` fallback.** When the API sends none, it now points to the code's
  real page (`https://coatipay.com/docs/errors/<code>`); it used to be
  `https://docs.coatipay.com`, which does not exist.
- `__version__` said `0.1.1`.

### Changed

- **`webhooks.verify` follows the rules shared by every CoatiPay SDK**
  (vectors in `@lacasoft/coatipay-protocol`): `t` must be all digits and appear
  once, spaces around parts are ignored, `tolerance` and `now` keyword
  arguments. It raises `WebhookSignatureError` — still a `ValueError`, with the
  same messages — carrying a `reason`: `malformed_header`,
  `timestamp_out_of_tolerance` or `no_matching_signature`.
- **API errors are raised with their class**: `AuthError`, `ValidationError`,
  `RoutingError`, `PaymentError` or `RateLimitError` by the code's catalog
  category, as in the JS SDK. All of them are `CoatiPaySDKError`, so existing
  `except CoatiPaySDKError` still catches them.

### Added

- `webhooks.list_dead_letters(limit=None)` and
  `webhooks.replay_dead_letter(id)`: deliveries that exhausted their retries,
  and sending one again.
- `classify_error`, the error classes, `WebhookSignatureError` and the
  `WebhookEventType` type.
- **Tests against the shared vectors** (`tests/vectors`, a copy of the latest
  published protocol's, checked in CI): the authorization nonce, the full
  ERC-3009 authorization per network (domain, message, digest, signature and
  API body — this SDK hashes EIP-712 by hand, and it matches), the 21 webhook
  cases and every error class. `coatipay/_catalogo.py` is generated from them.

## Withdrawn versions — 2026-09-27

**0.1.0 and 0.1.1 cannot complete a payment**: they sign with a random nonce, and the API
and the SettlementHub reject any authorization whose nonce is not the intent id (see 0.1.2
below). Both are **yanked on PyPI**: `pip install coatipay-sdk` no longer picks them. Use
**0.1.2 or later**.

The old `openrelay` package (the name before the rebrand) is yanked too.

## 0.1.2 — 2026-09-01

### ⚠️ Breaking: `intentId` is now required when signing

The SettlementHub now requires the ERC-3009 authorization nonce to equal the
intent id. **Signatures produced by 0.1.1 and earlier are rejected on-chain**,
so upgrading is not optional if you are signing payments.

```diff
- nonce = generate_nonce()
- typed = build_authorization_typed_data(payer, amount, hub, chain, nonce=nonce)
+ typed = build_authorization_typed_data(payer, amount, hub, chain, intent_id=intent_id)
```

Pass the **textual** intent id (`pi_…`) exactly as the API returns it. The SDK
derives the on-chain nonce itself; you do not need to hash anything. `intent_id_to_bytes32` is
exported if you want to verify the derivation.

The random-nonce generator has been **removed**. There is no migration path that
keeps it: a random nonce is precisely the defect this release fixes.

### Why

A signed authorization was not bound to any particular intent. Because USDC
enforces `msg.sender == to`, the signed `to` is always the hub and can never
name a merchant — so the payment destination was decided by calldata that the
routing node controls. A malicious node could redirect a payment and keep
**997 of every 1000 USDC**.

Reported externally and fixed in ADR-004. Full write-up:
https://github.com/lacasoft/coatipay-protocol/blob/master/audits/adr/004-auth-binding-y-retirada-de-disputas.md

### Also

- Protocol fee is now **1.5%** (ADR-005), split 70/30 as before: 1.05% to the
  routing node, 0.45% to the treasury.
