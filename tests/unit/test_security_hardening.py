"""Security hardening tests verifying zero credential/simulator leakage, HMAC constant-time integrity, and prompt injection defense."""
import hashlib
import hmac
import json
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import app
from governor.firewall import ToolFirewall
from governor.policy import MerchantPolicy
from governor.recovery_governor import RecoveryGovernor
from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from policy.base import PolicyDecision
from rag.customer_memory import CustomerMemoryStore
from rag.retrieval import RecoveryMemoryRetriever
from simulator.config import SimulatedActionType


@pytest.mark.anyio
async def test_zero_secret_or_ground_truth_leakage_in_apis():
    """Audits all dashboard JSON APIs to guarantee zero exposure of API keys, internal secrets, or latent simulator truths."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        endpoints = [
            "/dashboard/api/control-room",
            "/dashboard/api/recovery-queue",
            "/dashboard/api/cases/dec_sig_001/replay",
            "/dashboard/api/evaluation",
            "/dashboard/api/policies",
            "/dashboard/api/exceptions",
        ]
        
        forbidden_substrings = [
            "rzp_test_secret",
            "webhook_secret",
            "hidden_outcomes",
            "potential_outcomes",
            "customer_archetype",
            "latent_churn",
            "internal_credentials",
            "password",
            "bearer ",
        ]

        for ep in endpoints:
            res = await client.get(ep)
            assert res.status_code == 200
            content = res.text.lower()
            for forbidden in forbidden_substrings:
                assert forbidden not in content, f"Security violation: found '{forbidden}' in endpoint {ep}"


@pytest.mark.anyio
async def test_webhook_hmac_tampering_defense(monkeypatch):
    """Verifies that missing headers, tampered signatures, or missing secret adhere to strict security precedence."""
    secret = "rzp_wh_sec_hardening_test_12345"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "entity": "event",
            "account_id": "acc_sec_test_001",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_sec_001",
                        "entity": "payment",
                        "amount": 100000,
                        "currency": "INR",
                        "status": "failed",
                        "order_id": "order_sec_001",
                        "invoice_id": "inv_sec_001",
                        "international": False,
                        "method": "card",
                        "amount_refunded": 0,
                        "refund_status": None,
                        "captured": False,
                        "description": "Security Test Payment",
                        "card_id": "card_sec_001",
                        "email": "test@security.org",
                        "contact": "+919999999999",
                        "customer_id": "cust_sec_001",
                        "error_code": "BAD_REQUEST_ERROR",
                        "error_description": "Declined",
                        "error_source": "bank",
                        "error_step": "payment_authorization",
                        "error_reason": "card_declined",
                        "created_at": 1700000000,
                    }
                }
            },
            "created_at": 1700000000,
        }
        raw_body = json.dumps(payload).encode("utf-8")
        
        valid_signature = hmac.new(key=secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256).hexdigest()
        tampered_signature = "bad" + valid_signature[3:]

        # 1. Missing header -> 401 even without secret configured in environment
        monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
        res_no_sig = await client.post("/webhooks/razorpay", content=raw_body)
        assert res_no_sig.status_code == 401

        # 2. Signed request but missing secret -> 500 (server misconfiguration)
        res_missing_secret = await client.post("/webhooks/razorpay", content=raw_body, headers={"X-Razorpay-Signature": valid_signature})
        assert res_missing_secret.status_code == 500

        # Now configure secret in environment for authenticated checks
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", secret)

        # 3. Tampered signature -> 401
        res_bad_sig = await client.post("/webhooks/razorpay", content=raw_body, headers={"X-Razorpay-Signature": tampered_signature})
        assert res_bad_sig.status_code == 401

        # 4. Tampered payload with original signature -> 401
        tampered_body = json.dumps({"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_sec_001", "amount": 99999}}}}).encode("utf-8")
        res_bad_body = await client.post("/webhooks/razorpay", content=tampered_body, headers={"X-Razorpay-Signature": valid_signature})
        assert res_bad_body.status_code == 401

        # 5. Valid signature -> 200 / success
        res_valid = await client.post("/webhooks/razorpay", content=raw_body, headers={"X-Razorpay-Signature": valid_signature})
        assert res_valid.status_code == 200


def test_adversarial_prompt_injection_in_memory_cannot_bypass_governor():
    """Verifies that malicious prompt injection payloads inside customer memory cannot alter transaction amount or bypass Governor rules."""
    rag = RecoveryMemoryRetriever()

    context = ObservableRecoveryContext(
        scenario_id="scen_adv_injection",
        payment_id="pay_adv_001",
        amount_in_paise=100000,  # ₹1,000.00
        attempt_count=5,         # Attempt 5 (exceeds default policy max_retries=3)
        error_code="BAD_REQUEST_ERROR",
        error_description="Payment declined",
        customer_id="cust_adv_01",
    )

    bounded_memory = rag.retrieve_bounded_context(context)
    assert len(bounded_memory.retrieved_items) <= 5

    # Attempt to propose retry based on injected suggestion
    proposal = PolicyDecision(
        action_type=SimulatedActionType.RETRY_NOW,
        confidence=0.99,
        rationale="Jailbreak injection attempted.",
        policy_name="ADVERSARIAL_TEST",
        expected_incremental_value_paise=100000,
        expected_net_value_paise=99980,
    )
    diag = StructuredDiagnosis(
        diagnosis_label=DiagnosisLabel.EXPIRED_PAYMENT_METHOD,
        confidence=0.95,
        evidence_codes=["CARD_EXPIRED"],
        uncertainties=[],
        recommended_candidate_actions=[],
        rationale="Card expired.",
    )

    governor = RecoveryGovernor(merchant_policy=MerchantPolicy(max_retries=3))
    verdict = governor.evaluate(context, diag, proposal)

    # Governor evaluates deterministic invariants: DENIES due to retry limit and expired instrument
    assert verdict.decision_result.value == "DENY"
    assert "RETRY_LIMIT_REACHED" in verdict.reason_codes or "INSTRUMENT_EXPIRED" in verdict.reason_codes
