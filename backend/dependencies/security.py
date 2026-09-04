"""HMAC SHA-256 Webhook signature verification dependency for Razorpay."""
import hashlib
import hmac
import os
from fastapi import HTTPException, Request, status


async def verify_razorpay_signature(request: Request) -> bytes:
    """Verify Razorpay webhook HMAC SHA-256 signature against the raw request body.

    CRITICAL SECURITY DESIGN:
    1. Reads the raw request body directly using `await request.body()`.
    2. Never parses JSON prior to HMAC verification to preserve exact whitespace and key ordering.
    3. Uses `hmac.compare_digest` for constant-time comparison to prevent side-channel timing attacks.
    4. Retrieves secret dynamically from the `RAZORPAY_WEBHOOK_SECRET` environment variable.

    Args:
        request: The incoming FastAPI request instance.

    Returns:
        The verified raw bytes of the request body.

    Raises:
        HTTPException(401): If signature header is missing or signature verification fails.
        HTTPException(500): If the server webhook secret is unconfigured.
    """
    signature = request.headers.get("X-Razorpay-Signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required X-Razorpay-Signature header",
        )

    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty request payload cannot be verified",
        )

    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfiguration: RAZORPAY_WEBHOOK_SECRET is not configured",
        )

    expected_signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    return raw_body
