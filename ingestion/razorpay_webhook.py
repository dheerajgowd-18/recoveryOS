"""Razorpay webhook signature verification and payload normalization layer."""
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional, Tuple

from domain.events import WebhookPayload

logger = logging.getLogger("recoveryos.ingestion.razorpay_webhook")


class InvalidWebhookSignatureError(ValueError):
    """Raised when an incoming webhook's HMAC SHA-256 signature fails validation."""
    pass


class WebhookPayloadValidationError(ValueError):
    """Raised when an incoming webhook payload has invalid JSON structure or missing fields."""
    pass


def validate_razorpay_signature(raw_body: bytes, signature: Optional[str], secret: Optional[str]) -> bool:
    """Strictly validates a Razorpay webhook HMAC SHA-256 signature.

    Args:
        raw_body: Exact raw bytes of the incoming request body (preserves byte ordering & whitespace).
        signature: The hexadecimal signature provided in the 'X-Razorpay-Signature' header.
        secret: The configured webhook shared secret.

    Returns:
        True if signature matches expected HMAC SHA-256 digest; False otherwise.
    """
    if not secret or not signature or not raw_body:
        return False

    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def parse_and_validate_razorpay_webhook(
    raw_body: bytes,
    signature: Optional[str],
    secret: Optional[str],
) -> WebhookPayload:
    """Verifies signature and deserializes raw body into canonical WebhookPayload domain envelope.

    Args:
        raw_body: Exact raw bytes of incoming request.
        signature: 'X-Razorpay-Signature' header value.
        secret: Webhook shared secret.

    Returns:
        Normalized WebhookPayload instance ready for state reconciliation.

    Raises:
        InvalidWebhookSignatureError: If signature verification fails or secret is unconfigured.
        WebhookPayloadValidationError: If JSON is malformed or schema validation fails.
    """
    if not validate_razorpay_signature(raw_body, signature, secret):
        logger.warning("Rejected Razorpay webhook with invalid or missing HMAC SHA-256 signature.")
        raise InvalidWebhookSignatureError("Invalid or missing Razorpay webhook signature (X-Razorpay-Signature)")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        logger.warning("Failed to decode webhook JSON: %s", err)
        raise WebhookPayloadValidationError(f"Malformed JSON payload: {err}") from err

    try:
        return WebhookPayload.model_validate(data)
    except Exception as err:
        logger.warning("Failed to validate WebhookPayload schema: %s", err)
        raise WebhookPayloadValidationError(f"Invalid Razorpay webhook structure: {err}") from err
