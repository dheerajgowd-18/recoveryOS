"""Webhook ingestion routes for Razorpay events."""
import json
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.dependencies.security import verify_razorpay_signature
from backend.services.ingestion_service import IngestionResult, IngestionService, get_ingestion_service
from domain.events import WebhookPayload
from ingestion.reconciler import ReconciliationError

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class WebhookIngestionResponse(BaseModel):
    """Structured response for successfully ingested webhooks."""
    model_config = ConfigDict(extra="forbid")

    status: str
    event: str
    event_id: str
    is_duplicate: bool
    entity_id: Optional[str] = None
    reconciled_state: Optional[str] = None
    aggregate_version: Optional[int] = None
    received: bool = True


@router.post(
    "/razorpay",
    response_model=WebhookIngestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest Razorpay webhook",
    description="Secured endpoint that ingests, verifies, and parses incoming Razorpay event webhooks.",
)
async def ingest_razorpay_webhook(
    raw_body: bytes = Depends(verify_razorpay_signature),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
) -> WebhookIngestionResponse:
    """Ingest, verify, and reconcile Razorpay webhooks with idempotency safeguards."""
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

    try:
        result = await ingestion_service.process_webhook(payload)
    except ReconciliationError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        ) from err

    return WebhookIngestionResponse(
        status=result.status,
        event=result.event,
        event_id=result.event_id,
        is_duplicate=result.is_duplicate,
        entity_id=result.entity_id,
        reconciled_state=result.reconciled_state,
        aggregate_version=result.aggregate_version,
        received=True,
    )
