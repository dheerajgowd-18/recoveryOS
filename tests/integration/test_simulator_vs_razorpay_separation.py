"""Integration tests verifying complete architectural separation between offline simulation and real Razorpay gateway/webhook layers."""
import hashlib
import hmac
import json
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app
from evaluation.benchmark_runner import BenchmarkConfig, BenchmarkRunner
from evaluation.harness import EvaluationExecutionMode
from simulator.generator import Simulator


class TestSimulationVsRazorpaySeparation:
    """Verifies that synthetic simulation is strictly decoupled from live Razorpay network infrastructure."""

    def test_benchmark_runs_100_percent_offline_without_network_credentials(self, monkeypatch):
        """BenchmarkRunner must execute multi-seed synthetic evaluation completely offline without any API keys."""
        # Strip all gateway/API credentials
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
        monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)

        cfg = BenchmarkConfig(
            dev_seeds=[42],
            holdout_seeds=[43],
            num_scenarios=5,
            execution_mode=EvaluationExecutionMode.OFFLINE_REPLAY,
        )
        runner = BenchmarkRunner(config=cfg)
        result = runner.run_benchmark()

        assert result is not None
        assert result.combined_split.total_scenarios == 10
        assert "RECOVERYOS_DETERMINISTIC_V0" in result.combined_split.policy_results

    @pytest.mark.anyio
    async def test_webhook_receiver_signature_rejection_and_acceptance(self, monkeypatch):
        """Webhook endpoint rejects invalid/tampered signatures with 401 and accepts verified payloads with 200."""
        secret = "test_webhook_secret_key_12345"
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", secret)

        valid_payload = {
            "entity": "event",
            "account_id": "acc_test_123",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_sep_test_001",
                        "entity": "payment",
                        "amount": 50000,
                        "currency": "INR",
                        "status": "failed",
                        "order_id": "order_sep_001",
                        "method": "card",
                        "captured": False,
                        "description": "Test failure",
                        "error_code": "BAD_REQUEST_ERROR",
                        "error_description": "Card expired",
                        "error_source": "bank",
                        "error_step": "payment_authorization",
                        "error_reason": "card_expired",
                        "created_at": 1700000000,
                    }
                }
            },
            "created_at": 1700000000,
        }
        body_bytes = json.dumps(valid_payload).encode("utf-8")

        # Compute valid HMAC SHA-256
        valid_sig = hmac.new(
            key=secret.encode("utf-8"),
            msg=body_bytes,
            digestmod=hashlib.sha256,
        ).hexdigest()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Valid signature -> 200 OK
            res_valid = await client.post(
                "/webhooks/razorpay",
                content=body_bytes,
                headers={"X-Razorpay-Signature": valid_sig, "Content-Type": "application/json"},
            )
            assert res_valid.status_code == 200
            data = res_valid.json()
            assert data["status"] == "ok"
            assert data["event"] == "payment.failed"

            # 2. Duplicate event -> 200 OK with is_duplicate=True
            res_dup = await client.post(
                "/webhooks/razorpay",
                content=body_bytes,
                headers={"X-Razorpay-Signature": valid_sig, "Content-Type": "application/json"},
            )
            assert res_dup.status_code == 200
            assert res_dup.json()["is_duplicate"] is True

            # 3. Tampered body / invalid signature -> 401 Unauthorized
            res_tampered = await client.post(
                "/webhooks/razorpay",
                content=b'{"tampered": true}',
                headers={"X-Razorpay-Signature": valid_sig, "Content-Type": "application/json"},
            )
            assert res_tampered.status_code == 401

            # 4. Missing signature header -> 401 Unauthorized
            res_missing = await client.post(
                "/webhooks/razorpay",
                content=body_bytes,
                headers={"Content-Type": "application/json"},
            )
            assert res_missing.status_code == 401
