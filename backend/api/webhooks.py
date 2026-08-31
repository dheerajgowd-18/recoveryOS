"""Webhook ingestion routes for Razorpay events."""
import json
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError

from backend.dependencies.security import verify_razorpay_signature
from domain.events import WebhookPayload

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class WebhookIngestionResponse(BaseModel):
    """Structured response for successfully ingested webhooks."""
    status: str
    event: str
    received: bool


@router.post(
    "/razorpay",
    response_model=WebhookIngestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest Razorpay webhook",
    description="Secured endpoint that ingests, verifies, and parses incoming Razorpay event webhooks.",
)
async def ingest_razorpay_webhook(
    raw_body: bytes = Depends(verify_razorpay_signature),
) -> WebhookIngestionResponse:
    """Ingest and validate Razorpay webhooks after HMAC signature verification.

    Note: The raw request body is verified in `verify_razorpay_signature` before parsing.
    """
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed JSON payload: {str(err)}",
        ) from err

    try:
        payload = WebhookPayload.model_validate(data)
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid payload structure: {err.errors()}",
        ) from err

    return WebhookIngestionResponse(
        status="ok",
        event=payload.event,
        received=True,
    )
