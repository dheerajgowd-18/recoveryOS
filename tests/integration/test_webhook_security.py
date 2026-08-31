"""Integration tests verifying HMAC SHA-256 webhook security and endpoint contracts."""
import hashlib
import hmac
import json
import os
from typing import Dict
import pytest
from fastapi.testclient import TestClient

from backend.app import app

TEST_SECRET = "test_webhook_secret_key_xyz987"


def generate_razorpay_signature(secret: str, payload_bytes: bytes) -> str:
    """Helper to compute valid Razorpay HMAC SHA-256 signature."""
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()


@pytest.fixture(autouse=True)
def setup_webhook_secret(monkeypatch: pytest.MonkeyPatch):
    """Set RAZORPAY_WEBHOOK_SECRET in environment for tests."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", TEST_SECRET)


@pytest.fixture
def sample_webhook_payload() -> Dict:
    """Sample realistic Razorpay payment.failed webhook dictionary."""
    return {
        "entity": "event",
        "account_id": "acc_live_test_001",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_failed_999",
                    "entity": "payment",
                    "amount": 199900,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_test_999",
                    "invoice_id": "inv_test_999",
                    "international": False,
                    "method": "card",
                    "amount_refunded": 0,
                    "refund_status": None,
                    "captured": False,
                    "description": "Subscription Renewal",
                    "card_id": "card_test_123",
                    "email": "customer@business.com",
                    "contact": "+919876543210",
                    "customer_id": "cust_test_123",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment was declined by issuing bank",
                    "error_source": "bank",
                    "error_step": "payment_authorization",
                    "error_reason": "insufficient_funds",
                    "created_at": 1700000000,
                }
            }
        },
        "created_at": 1700000000,
    }


class TestWebhookSecurity:
    """Test suite for HMAC SHA-256 webhook ingestion security."""

    def test_valid_signature_returns_200(self, sample_webhook_payload: Dict) -> None:
        client = TestClient(app)
        raw_body = json.dumps(sample_webhook_payload).encode("utf-8")
        valid_signature = generate_razorpay_signature(TEST_SECRET, raw_body)

        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": valid_signature,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["event"] == "payment.failed"
        assert data["received"] is True

    def test_invalid_signature_returns_401(self, sample_webhook_payload: Dict) -> None:
        client = TestClient(app)
        raw_body = json.dumps(sample_webhook_payload).encode("utf-8")
        invalid_signature = "a" * 64

        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": invalid_signature,
            },
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid webhook signature"

    def test_missing_signature_header_returns_401(self, sample_webhook_payload: Dict) -> None:
        client = TestClient(app)
        raw_body = json.dumps(sample_webhook_payload).encode("utf-8")

        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 401
        assert "Missing required X-Razorpay-Signature header" in response.json()["detail"]

    def test_tampered_payload_returns_401(self, sample_webhook_payload: Dict) -> None:
        client = TestClient(app)
        original_body = json.dumps(sample_webhook_payload).encode("utf-8")
        valid_signature_for_original = generate_razorpay_signature(TEST_SECRET, original_body)

        # Tamper payload by modifying amount
        tampered_dict = sample_webhook_payload.copy()
        tampered_dict["account_id"] = "acc_malicious_attacker"
        tampered_body = json.dumps(tampered_dict).encode("utf-8")

        # Submit tampered body with original signature
        response = client.post(
            "/webhooks/razorpay",
            content=tampered_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": valid_signature_for_original,
            },
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid webhook signature"

    def test_empty_payload_returns_401(self) -> None:
        client = TestClient(app)
        raw_body = b""
        signature = generate_razorpay_signature(TEST_SECRET, raw_body)

        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
            },
        )

        assert response.status_code == 401
        assert "Empty request payload cannot be verified" in response.json()["detail"]

    def test_unconfigured_secret_returns_500(
        self, monkeypatch: pytest.MonkeyPatch, sample_webhook_payload: Dict
    ) -> None:
        monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
        client = TestClient(app)
        raw_body = json.dumps(sample_webhook_payload).encode("utf-8")

        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": "some_signature",
            },
        )

        assert response.status_code == 500
        assert "RAZORPAY_WEBHOOK_SECRET is not configured" in response.json()["detail"]

    def test_malformed_json_returns_400(self) -> None:
        client = TestClient(app)
        malformed_bytes = b"{\"entity\": \"event\", broken_json"
        valid_signature = generate_razorpay_signature(TEST_SECRET, malformed_bytes)

        response = client.post(
            "/webhooks/razorpay",
            content=malformed_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": valid_signature,
            },
        )

        assert response.status_code == 400
        assert "Malformed JSON payload" in response.json()["detail"]

    def test_invalid_schema_returns_422(self) -> None:
        client = TestClient(app)
        invalid_schema_dict = {"event": "payment.failed"}  # Missing required fields
        raw_body = json.dumps(invalid_schema_dict).encode("utf-8")
        valid_signature = generate_razorpay_signature(TEST_SECRET, raw_body)

        response = client.post(
            "/webhooks/razorpay",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": valid_signature,
            },
        )

        assert response.status_code == 422
        assert "Invalid payload structure" in response.json()["detail"]

    def test_health_check_endpoint(self) -> None:
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
