import asyncio
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import httpx

from backend.app import app
from domain.enums import PaymentState
from execution.executor import ExecutionContext
from execution.razorpay_adapter import RazorpayAdapter
from ingestion.razorpay_webhook import (
    InvalidWebhookSignatureError,
    WebhookPayloadValidationError,
    parse_and_validate_razorpay_webhook,
    validate_razorpay_signature,
)
from simulator.config import SimulatedActionType, SimulatorConfig
from simulator.generator import Simulator

TEST_WEBHOOK_SECRET = "rzp_test_secret_key_abc123"


def compute_signature(payload_bytes: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    """Computes exact HMAC SHA-256 signature for test payload."""
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()


@pytest.fixture
def test_client(monkeypatch: pytest.MonkeyPatch):
    """Provides a TestClient with configured webhook secret."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    return TestClient(app)


class TestRazorpayWebhookValidation:
    """Validates HMAC SHA-256 signature verification and payload normalization."""

    def test_signature_validation_helper_success(self):
        """validate_razorpay_signature returns True on matching signature."""
        body = b'{"event": "payment.failed", "account_id": "acc_001"}'
        sig = compute_signature(body, TEST_WEBHOOK_SECRET)
        assert validate_razorpay_signature(body, sig, TEST_WEBHOOK_SECRET) is True

    def test_signature_validation_helper_failure_on_tampering(self):
        """validate_razorpay_signature returns False on tampered body or bad signature."""
        body = b'{"event": "payment.failed", "account_id": "acc_001"}'
        tampered = b'{"event": "payment.failed", "account_id": "acc_002"}'
        sig = compute_signature(body, TEST_WEBHOOK_SECRET)
        assert validate_razorpay_signature(tampered, sig, TEST_WEBHOOK_SECRET) is False
        assert validate_razorpay_signature(body, "bad_sig_12345", TEST_WEBHOOK_SECRET) is False
        assert validate_razorpay_signature(body, None, TEST_WEBHOOK_SECRET) is False

    def test_parse_and_validate_webhook_success(self):
        """parse_and_validate_razorpay_webhook parses valid JSON into WebhookPayload."""
        raw_dict = {
            "entity": "event",
            "account_id": "acc_test_merchant_01",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_001",
                        "amount": 250000,
                        "currency": "INR",
                        "status": "failed",
                        "created_at": 1717200000,
                        "error_code": "BAD_REQUEST_ERROR",
                        "error_description": "Payment failed at bank gateway",
                    }
                }
            },
            "created_at": 1717200000,
        }
        body = json.dumps(raw_dict).encode("utf-8")
        sig = compute_signature(body, TEST_WEBHOOK_SECRET)

        payload = parse_and_validate_razorpay_webhook(body, sig, TEST_WEBHOOK_SECRET)
        assert payload.account_id == "acc_test_merchant_01"
        assert payload.event == "payment.failed"
        assert payload.payload.payment.entity.id == "pay_test_001"

    def test_parse_and_validate_webhook_invalid_signature_raises(self):
        """parse_and_validate_razorpay_webhook raises InvalidWebhookSignatureError on bad signature."""
        body = b'{"event": "payment.failed"}'
        with pytest.raises(InvalidWebhookSignatureError):
            parse_and_validate_razorpay_webhook(body, "invalid_sig", TEST_WEBHOOK_SECRET)


class TestRazorpayWebhookEndpointIntegration:
    """Integration tests hitting POST /webhooks/razorpay."""

    def test_valid_webhook_signature_returns_200_and_ingests(self, test_client: TestClient):
        """Valid webhook signature receives HTTP 200 and successful ingestion receipt."""
        raw_dict = {
            "entity": "event",
            "account_id": "acc_rzp_live_test",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_integ_test_001",
                        "amount": 150000,
                        "currency": "INR",
                        "status": "failed",
                        "created_at": 1717200100,
                        "error_code": "GATEWAY_ERROR",
                        "error_description": "Gateway connection timeout",
                    }
                }
            },
            "created_at": 1717200100,
        }
        body = json.dumps(raw_dict).encode("utf-8")
        sig = compute_signature(body, TEST_WEBHOOK_SECRET)

        response = test_client.post(
            "/webhooks/razorpay",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": sig,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["event"] == "payment.failed"
        assert data["entity_id"] == "pay_integ_test_001"
        assert data["received"] is True

    def test_invalid_webhook_signature_returns_401(self, test_client: TestClient):
        """Invalid webhook signature receives HTTP 401 Unauthorized."""
        body = b'{"event": "payment.failed", "account_id": "acc_test"}'
        response = test_client.post(
            "/webhooks/razorpay",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": "invalid_signature_hex_12345",
            },
        )
        assert response.status_code == 401
        assert "Invalid webhook signature" in response.json()["detail"]


class TestRazorpayAdapterExecution:
    """Validates RazorpayAdapter fail-closed guards, mocked API calls, and domain mapping."""

    def test_adapter_missing_credentials_fails_closed_safely(self):
        """Adapter instantiated without credentials fails closed safely without unhandled exceptions."""
        adapter = RazorpayAdapter(key_id=None, key_secret=None)
        assert adapter.has_valid_credentials is False

        sim = Simulator()
        scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=1))
        scenario = scenarios[0]

        context = ExecutionContext(
            scenario=scenario,
            attempt_count=1,
            current_epoch=1717200000,
        )

        result = asyncio.run(adapter.execute(SimulatedActionType.PAYMENT_LINK, context))
        assert result.success is False
        assert result.recovered is False
        assert "fail-closed" in result.message.lower()

    def test_adapter_placeholder_credentials_fails_closed(self):
        """Adapter with placeholder credentials fails closed."""
        adapter = RazorpayAdapter(key_id="your_razorpay_test_key_id", key_secret="your_razorpay_test_key_secret")
        assert adapter.has_valid_credentials is False

        # fetch_payment_status should return None without throwing
        res = asyncio.run(adapter.fetch_payment_status("pay_test_999"))
        assert res is None

    def test_adapter_mocked_payment_status_api_call(self):
        """Adapter correctly calls Razorpay API and maps response to PaymentEntity."""
        adapter = RazorpayAdapter(key_id="rzp_test_validKey123", key_secret="validSecret456")
        assert adapter.has_valid_credentials is True

        mock_payload = {
            "id": "pay_live_test_001",
            "entity": "payment",
            "amount": 500000,
            "currency": "INR",
            "status": "captured",
            "order_id": "order_test_001",
            "invoice_id": "inv_test_001",
            "international": False,
            "method": "card",
            "amount_refunded": 0,
            "refund_status": None,
            "captured": True,
            "description": "Subscription charge",
            "card_id": "card_test_001",
            "bank": None,
            "wallet": None,
            "vpa": None,
            "email": "user@example.com",
            "contact": "+919876543210",
            "customer_id": "cust_001",
            "created_at": 1717200500,
        }

        mock_response = httpx.Response(
            status_code=200,
            json=mock_payload,
            request=httpx.Request("GET", "https://api.razorpay.com/v1/payments/pay_live_test_001"),
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            entity = asyncio.run(adapter.fetch_payment_status("pay_live_test_001"))

            assert entity is not None
            assert entity.id == "pay_live_test_001"
            assert entity.status == PaymentState.CAPTURED
            assert entity.amount == 500000
            assert entity.captured is True

    def test_adapter_mocked_create_payment_link_execution(self):
        """Adapter correctly triggers payment link creation and emits ExecutionResult."""
        adapter = RazorpayAdapter(key_id="rzp_test_validKey123", key_secret="validSecret456")

        mock_link_payload = {
            "id": "plink_test_001",
            "amount": 200000,
            "currency": "INR",
            "status": "created",
            "short_url": "https://rzp.io/i/testlink",
        }

        mock_response = httpx.Response(
            status_code=200,
            json=mock_link_payload,
            request=httpx.Request("POST", "https://api.razorpay.com/v1/payment_links"),
        )

        sim = Simulator()
        scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=1))
        scenario = scenarios[0]

        context = ExecutionContext(
            scenario=scenario,
            attempt_count=1,
            current_epoch=1717200000,
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = asyncio.run(adapter.execute(SimulatedActionType.PAYMENT_LINK, context))

            assert result.success is True
            assert result.action_type == SimulatedActionType.PAYMENT_LINK
            assert "plink_test_001" in result.message
            assert result.action_cost_paise == 20
