"""FastAPI application entrypoint for RecoveryOS."""
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from backend.api.webhooks import router as webhooks_router
from dashboard.routes import router as dashboard_router

# Load environment variables from .env if present
load_dotenv()


class HealthCheckResponse(BaseModel):
    """Health check payload."""
    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    """Factory creating configured FastAPI instance."""
    app = FastAPI(
        title="RecoveryOS Operations & Ingestion API",
        description="Autonomous AI revenue recovery platform - Ingestion, Operations Console & Governance engine",
        version="0.1.0",
    )

    app.include_router(webhooks_router)
    app.include_router(dashboard_router)

    @app.get("/health", response_model=HealthCheckResponse, tags=["Health"])
    async def health_check() -> HealthCheckResponse:
        """Health check endpoint to verify service readiness."""
        return HealthCheckResponse(
            status="healthy",
            service="RecoveryOS Ingestion API",
            version="0.1.0",
        )

    return app


app = create_app()
