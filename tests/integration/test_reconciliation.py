"""Integration tests for state reconciliation, out-of-order handling, duplicate event idempotency, and terminal protection."""
import hashlib
import hmac
import json
import os
from typing import Dict
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.ingestion_service import IngestionService, get_ingestion_service
from domain.enums import PaymentState, SubscriptionState
from ingestion.idempotency import InMemoryIdempotencyTracker
from ingestion.reconciler import InvalidStateTransitionError, StateReconciler
from ingestion.store import InMemoryEventStore

TEST_SECRET = "reconciliation_test_secret_key_123"


def compute_sig(payload_bytes: bytes) -> str:
    """Compute HMAC SHA-256 signature with test secret."""
    return hmac.new(
        key=TEST_SECRET.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()


@pytest.fixture(autouse=True)
def setup_environment(monkeypatch: pytest.MonkeyPatch):
    """Ensure secret is set and fresh in-memory service is injected for each test."""
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", TEST_SECRET)
    service = IngestionService(
        event_store=InMemoryEventStore(),
        idempotency_tracker=InMemoryIdempotencyTracker(),
        reconciler=StateReconciler(),
    )
    app.dependency_overrides[get_ingestion_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


def make_payment_webhook(
    event_type: str,
    payment_id: str,
    status_str: str,
    created_at_epoch: int,
    account_id: str = "acc_test_recon",
) -> Dict:
    """Factory helper creating valid Razorpay payment webhook dicts."""
    return {
        "entity": "event",
        "account_id": account_id,
        "event": event_type,
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 299900,
                    "currency": "INR",
                    "status": status_str,
                    "order_id": "order_recon_001",
                    "created_at": created_at_epoch,
                }
            }
        },
        "created_at": created_at_epoch,
    }


def make_subscription_webhook(
    event_type: str,
    subscription_id: str,
    status_str: str,
    created_at_epoch: int,
    account_id: str = "acc_test_recon",
) -> Dict:
    """Factory helper creating valid Razorpay subscription webhook dicts."""
    return {
        "entity": "event",
        "account_id": account_id,
        "event": event_type,
        "contains": ["subscription"],
        "payload": {
            "subscription": {
                "entity": {
                    "id": subscription_id,
                    "entity": "subscription",
                    "plan_id": "plan_recon_pro",
                    "status": status_str,
                    "quantity": 1,
                    "created_at": created_at_epoch,
                }
            }
        },
        "created_at": created_at_epoch,
    }


class TestReconciliationScenarios:
    """Adversarial fintech reconciliation test cases."""

    def test_duplicate_webhook_idempotency(self, setup_environment: IngestionService) -> None:
        """Scenario: Exact same webhook sent twice. Verified state transitions occur only once."""
        client = TestClient(app)
        service = setup_environment
        payload = make_payment_webhook("payment.failed", "pay_dup_001", "failed", 1700000000)
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(body)}

        # First request
        res1 = client.post("/webhooks/razorpay", content=body, headers=headers)
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["is_duplicate"] is False
        assert data1["reconciled_state"] == "failed"
        assert data1["aggregate_version"] == 1

        # Second identical request
        res2 = client.post("/webhooks/razorpay", content=body, headers=headers)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["is_duplicate"] is True
        assert data2["reconciled_state"] == "failed"
        assert data2["aggregate_version"] == 1

    def test_out_of_order_events_captured_before_authorized(self, setup_environment: IngestionService) -> None:
        """Scenario: payment.captured (t=200) arrives BEFORE payment.authorized (t=100).

        Final state must deterministically resolve to CAPTURED based on occurred_at.
        """
        client = TestClient(app)
        payment_id = "pay_ooo_001"

        # 1. Received FIRST: payment.captured at epoch 1700000200
        captured_payload = make_payment_webhook("payment.captured", payment_id, "captured", 1700000200)
        captured_body = json.dumps(captured_payload).encode("utf-8")
        res1 = client.post(
            "/webhooks/razorpay",
            content=captured_body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(captured_body)},
        )
        assert res1.status_code == 200
        assert res1.json()["reconciled_state"] == "captured"

        # 2. Received SECOND: payment.authorized at epoch 1700000100 (earlier in business time)
        authorized_payload = make_payment_webhook("payment.authorized", payment_id, "authorized", 1700000100)
        authorized_body = json.dumps(authorized_payload).encode("utf-8")
        res2 = client.post(
            "/webhooks/razorpay",
            content=authorized_body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(authorized_body)},
        )
        assert res2.status_code == 200
        assert res2.json()["reconciled_state"] == "captured"

    def test_late_event_preserves_terminal_captured_state(self, setup_environment: IngestionService) -> None:
        """Scenario: payment.failed (t=100) -> payment.captured (t=200) -> delayed payment.failed (t=150).

        Terminal CAPTURED state must NOT be corrupted by the delayed failure event.
        """
        client = TestClient(app)
        payment_id = "pay_late_001"

        # 1. Event 1: payment.failed at t=100
        e1 = make_payment_webhook("payment.failed", payment_id, "failed", 1700000100)
        b1 = json.dumps(e1).encode("utf-8")
        client.post("/webhooks/razorpay", content=b1, headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(b1)})

        # 2. Event 2: payment.captured at t=200 (Success)
        e2 = make_payment_webhook("payment.captured", payment_id, "captured", 1700000200)
        b2 = json.dumps(e2).encode("utf-8")
        res2 = client.post("/webhooks/razorpay", content=b2, headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(b2)})
        assert res2.json()["reconciled_state"] == "captured"

        # 3. Event 3: Delayed retry failure for earlier attempt at t=150
        e3 = make_payment_webhook("payment.failed", payment_id, "failed", 1700000150)
        b3 = json.dumps(e3).encode("utf-8")
        res3 = client.post("/webhooks/razorpay", content=b3, headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(b3)})
        assert res3.status_code == 200
        # Must preserve CAPTURED
        assert res3.json()["reconciled_state"] == "captured"

    def test_invalid_state_transition_handling(self, setup_environment: IngestionService) -> None:
        """Scenario: Captured payment receives a subsequent forward failed event at a later timestamp.

        System must reject the invalid transition with 409 Conflict.
        """
        client = TestClient(app)
        payment_id = "pay_invalid_001"

        # 1. Captured payment at t=100
        e1 = make_payment_webhook("payment.captured", payment_id, "captured", 1700000100)
        b1 = json.dumps(e1).encode("utf-8")
        client.post("/webhooks/razorpay", content=b1, headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(b1)})

        # 2. Subsequent invalid event at t=200 attempting forward transition CAPTURED -> FAILED
        e2 = make_payment_webhook("payment.failed", payment_id, "failed", 1700000200)
        b2 = json.dumps(e2).encode("utf-8")
        res2 = client.post("/webhooks/razorpay", content=b2, headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(b2)})
        assert res2.status_code == 409
        assert "cannot transition from 'captured' to 'failed'" in res2.json()["detail"]

    def test_subscription_dunning_recovery_lifecycle(self, setup_environment: IngestionService) -> None:
        """Scenario: Subscription active -> halted (dunning) -> active (recovered)."""
        client = TestClient(app)
        sub_id = "sub_dunning_001"

        # 1. Activated at t=100
        e1 = make_subscription_webhook("subscription.activated", sub_id, "active", 1700000100)
        b1 = json.dumps(e1).encode("utf-8")
        res1 = client.post("/webhooks/razorpay", content=b1, headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(b1)})
        assert res1.json()["reconciled_state"] == "active"

        # 2. Halted due to failed dunning payment at t=200
        e2 = make_subscription_webhook("subscription.halted", sub_id, "halted", 1700000200)
        b2 = json.dumps(e2).encode("utf-8")
        res2 = client.post("/webhooks/razorpay", content=b2, headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(b2)})
        assert res2.json()["reconciled_state"] == "halted"

        # 3. Recovered payment reactivates subscription at t=300
        e3 = make_subscription_webhook("subscription.charged", sub_id, "active", 1700000300)
        b3 = json.dumps(e3).encode("utf-8")
        res3 = client.post("/webhooks/razorpay", content=b3, headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_sig(b3)})
        assert res3.json()["reconciled_state"] == "active"
