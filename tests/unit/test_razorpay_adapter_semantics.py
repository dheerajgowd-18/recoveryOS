"""Unit tests verifying RazorpayAdapter execution semantics and failure modes."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from domain.enums import PaymentState
from execution.executor import ExecutionContext
from execution.razorpay_adapter import RazorpayAdapter, RazorpayConfigurationError
from simulator.config import SimulatorConfig, SimulatedActionType
from simulator.generator import Simulator


@pytest.fixture
def sample_execution_context():
    sim = Simulator()
    scenario = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=1))[0]
    return ExecutionContext(
        scenario=scenario,
        attempt_count=1,
        current_epoch=1000,
    )


class TestRazorpayAdapterSemantics:
    """Verifies that RazorpayAdapter handles credentials, API failures, and action routing truthfully."""

    def test_initialization_without_credentials(self, monkeypatch):
        """Adapter initialized without credentials or with placeholders must report has_valid_credentials=False."""
        monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

        adapter = RazorpayAdapter(key_id="", key_secret="")
        assert adapter.has_valid_credentials is False

        placeholder_adapter = RazorpayAdapter(key_id="your_razorpay_test_key_id", key_secret="xxx")
        assert placeholder_adapter.has_valid_credentials is False

    @pytest.mark.anyio
    async def test_missing_credentials_raises_configuration_error_on_direct_api_calls(self):
        """Direct API calls in strict mode must raise RazorpayConfigurationError when credentials are missing."""
        adapter = RazorpayAdapter(key_id="", key_secret="", strict=True)

        with pytest.raises(RazorpayConfigurationError, match="missing or invalid"):
            await adapter.fetch_payment_status("pay_test_123")

        with pytest.raises(RazorpayConfigurationError, match="missing or invalid"):
            await adapter.create_payment_link("pay_test_123", 50000)

    @pytest.mark.anyio
    async def test_strict_mode_raises_on_unconfigured_execute(self, sample_execution_context):
        """In strict mode, attempting to execute active interventions without credentials must raise RazorpayConfigurationError."""
        strict_adapter = RazorpayAdapter(key_id="", key_secret="", strict=True)

        with pytest.raises(RazorpayConfigurationError, match="Missing valid API credentials in strict mode"):
            await strict_adapter.execute(SimulatedActionType.PAYMENT_LINK, sample_execution_context)

    @pytest.mark.anyio
    async def test_non_strict_mode_fails_closed_safely(self, sample_execution_context):
        """In non-strict mode, attempting active execution without credentials returns a safe failed ExecutionResult."""
        adapter = RazorpayAdapter(key_id="", key_secret="", strict=False)

        res = await adapter.execute(SimulatedActionType.PAYMENT_LINK, sample_execution_context)
        assert res.success is False
        assert "fail-closed" in res.message.lower()

    @pytest.mark.anyio
    async def test_no_action_always_succeeds_without_credentials(self, sample_execution_context):
        """NO_ACTION (deliberate abstention) executes with zero cost and does not require credentials."""
        adapter = RazorpayAdapter(key_id="", key_secret="", strict=True)

        res = await adapter.execute(SimulatedActionType.NO_ACTION, sample_execution_context)
        assert res.success is True
        assert res.action_cost_paise == 0
        assert res.recovered is False

    @pytest.mark.anyio
    async def test_unsupported_action_fails_clearly(self, sample_execution_context):
        """Actions not supported by the Razorpay adapter fail with clear error messages."""
        adapter = RazorpayAdapter(key_id="rzp_test_validkey", key_secret="valid_secret_123")

        mock_unsupported = MagicMock(action_type="manual_phone_call")
        res = await adapter.execute(mock_unsupported, sample_execution_context)
        assert res.success is False
        assert "Unsupported action type" in res.message

    @pytest.mark.anyio
    async def test_mocked_payment_link_creation(self, sample_execution_context):
        """Valid credentials dispatch authorized payment link request."""
        adapter = RazorpayAdapter(key_id="rzp_test_validkey", key_secret="valid_secret_123")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "plink_test_001", "status": "created", "short_url": "https://rzp.io/i/test"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            res = await adapter.execute(SimulatedActionType.PAYMENT_LINK, sample_execution_context)
            assert res.success is True
            assert "plink_test_001" in res.message
            assert res.action_cost_paise == 20

    @pytest.mark.anyio
    async def test_non_json_razorpay_error_response_handling(self, sample_execution_context):
        """When Razorpay returns non-JSON error HTML (e.g. 502/503 bad gateway), handle safely without NameError."""
        adapter = RazorpayAdapter(key_id="rzp_test_validkey", key_secret="valid_secret_123")

        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.text = "<html><body>502 Bad Gateway</body></html>"
        mock_resp.json.side_effect = ValueError("No JSON")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            res = await adapter.create_payment_link("pay_test_502", 50000)
            assert res["success"] is False
            assert res["status_code"] == 502
            assert "502 Bad Gateway" in res["error"]
