"""
Categoría de cada código de error de la API de CoatiPay.

GENERADO por scripts/generar_catalogo.py desde los vectores compartidos
(tests/vectors/errores.json). No editar a mano.
"""

CATEGORIAS: dict[str, str] = {
    "already_reviewed": "conflict",
    "amount_below_minimum": "validation",
    "authorization_expired": "validation",
    "authorization_not_bound_to_intent": "validation",
    "authorization_not_claimed": "not_found",
    "authorization_not_yet_valid": "validation",
    "chain_verification_failed": "payment",
    "email_taken": "conflict",
    "forbidden": "auth",
    "idempotency_key_reused": "conflict",
    "insufficient_payment": "payment",
    "insufficient_permissions": "auth",
    "intent_already_settled": "conflict",
    "intent_not_found": "not_found",
    "intent_not_payable": "conflict",
    "internal_error": "internal",
    "invalid_api_key": "auth",
    "invalid_payment_payload": "validation",
    "invalid_request": "validation",
    "invalid_session": "auth",
    "invalid_signer": "validation",
    "invalid_token": "auth",
    "invalid_webhook_url": "validation",
    "node_not_registered": "not_found",
    "node_unavailable": "routing",
    "nonce_already_used": "conflict",
    "not_found": "not_found",
    "payment_in_progress": "conflict",
    "rate_limited": "rate_limit",
    "session_required": "auth",
    "signature_unverifiable": "unavailable",
    "unsupported_chain": "validation",
    "unsupported_signature": "validation",
    "webhook_endpoint_deleted": "conflict",
    "x402_replay": "payment",
}
