"""Razorpay Test-Mode Gateway Execution Adapter.

Bridges RecoveryOS autonomous decisions with the live Razorpay Test API.
Implements fail-closed security guards, credential sanitization, and domain model mapping.
"""
import logging
import os
from typing import Any, Dict, Optional, Union
import httpx

from domain.actions import Action
from domain.enums import PaymentState
from domain.events import PaymentEntity, PaymentEvent
from execution.executor import ExecutionContext, ExecutionResult, RecoveryExecutor
from simulator.config import SimulatedActionType

logger = logging.getLogger("recoveryos.execution.razorpay_adapter")

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


class RazorpayAdapter(RecoveryExecutor):
    """Real Razorpay test-mode API adapter and recovery action executor."""

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        base_url: str = RAZORPAY_API_BASE,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._key_id = key_id or os.getenv("RAZORPAY_KEY_ID")
        self._key_secret = key_secret or os.getenv("RAZORPAY_KEY_SECRET")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def has_valid_credentials(self) -> bool:
        """Determines if credentials are configured and not placeholder values."""
        if not self._key_id or not self._key_secret:
            return False
        # Reject placeholder patterns
        placeholders = {
            "your_razorpay_test_key_id",
            "your_razorpay_test_key_secret",
            "placeholder",
            "test_key",
            "xxx",
        }
        if self._key_id.strip().lower() in placeholders or self._key_secret.strip().lower() in placeholders:
            return False
        if len(self._key_id.strip()) < 5 or len(self._key_secret.strip()) < 5:
            return False
        return True

    def _get_auth(self) -> Optional[httpx.BasicAuth]:
        """Constructs HTTP Basic Auth without exposing secrets in logs."""
        if not self.has_valid_credentials:
            return None
        return httpx.BasicAuth(self._key_id.strip(), self._key_secret.strip())

    async def fetch_payment_status(self, payment_id: str) -> Optional[PaymentEntity]:
        """Fetches live payment status from Razorpay API and normalizes to PaymentEntity domain model.

        Args:
            payment_id: Razorpay payment identifier (e.g. 'pay_123456').

        Returns:
            PaymentEntity domain model if found and authorized, None otherwise.
        """
        if not self.has_valid_credentials:
            logger.warning("fetch_payment_status called without valid Razorpay credentials. Failing closed.")
            return None

        url = f"{self.base_url}/payments/{payment_id}"
        auth = self._get_auth()

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url, auth=auth)
                if response.status_code == 200:
                    data = response.json()
                    return PaymentEntity.model_validate(data)
                elif response.status_code == 404:
                    logger.warning("Payment %s not found on Razorpay API (404).", payment_id)
                    return None
                else:
                    logger.warning("Razorpay API error fetching payment %s: HTTP %s", payment_id, response.status_code)
                    return None
        except Exception as err:
            logger.error("Network or parsing error fetching Razorpay payment %s: %s", payment_id, err)
            return None

    async def create_payment_link(
        self,
        payment_id: str,
        amount_paise: int,
        customer_details: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates an authorized Razorpay payment link for an invoice recovery.

        Args:
            payment_id: Identifier of the failing payment.
            amount_paise: Amount in paise to collect.
            customer_details: Optional dict containing name, email, contact.
            description: Customer-facing memo.

        Returns:
            Dict containing API response payload or failure indicator.
        """
        if not self.has_valid_credentials:
            logger.warning("create_payment_link called without valid Razorpay credentials. Failing closed.")
            return {"success": False, "error": "MISSING_CREDENTIALS"}

        url = f"{self.base_url}/payment_links"
        auth = self._get_auth()
        customer_details = customer_details or {}

        payload: Dict[str, Any] = {
            "amount": amount_paise,
            "currency": "INR",
            "accept_partial": False,
            "description": description or f"Recovery for failed payment {payment_id}",
            "reference_id": payment_id,
            "customer": {
                "name": customer_details.get("name", "Valued Customer"),
                "email": customer_details.get("email", "billing@customer.com"),
                "contact": customer_details.get("contact", "+919999999999"),
            },
            "notify": {
                "sms": True,
                "email": True,
            },
            "reminder_enable": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, auth=auth, json=payload)
                if response.status_code in (200, 201):
                    data = response.json()
                    return {"success": True, "data": data, "payment_link_id": data.get("id")}
                else:
                    logger.warning("Razorpay API error creating payment link for %s: HTTP %s", payment_id, response.status_code)
                    return {"success": False, "status_code": response.status_code, "error": "API_ERROR"}
        except Exception as err:
            logger.error("Exception creating Razorpay payment link for %s: %s", payment_id, err)
            return {"success": False, "error": str(err)}

    async def execute(
        self,
        action: Union[SimulatedActionType, Action],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Executes recovery action against Razorpay test API. Fails closed safely if unconfigured.

        Args:
            action: Selected recovery action.
            context: Scenario execution context.

        Returns:
            ExecutionResult outcome without throwing unhandled exceptions.
        """
        action_type = action if isinstance(action, SimulatedActionType) else SimulatedActionType(action.action_type)

        # Handle No Action immediately
        if action_type == SimulatedActionType.NO_ACTION:
            return ExecutionResult(
                success=True,
                action_type=SimulatedActionType.NO_ACTION,
                recovered=False,
                recovered_amount_paise=0,
                action_cost_paise=0,
                execution_timestamp_epoch=context.current_epoch,
                message="Deliberate abstention executed successfully (0 cost).",
            )

        # If credentials missing or unconfigured, fail closed gracefully
        if not self.has_valid_credentials:
            logger.warning("RazorpayAdapter invoked without valid credentials. Failing closed safely.")
            return ExecutionResult(
                success=False,
                action_type=action_type,
                recovered=False,
                recovered_amount_paise=0,
                action_cost_paise=0,
                execution_timestamp_epoch=context.current_epoch,
                message="Razorpay test credentials missing or placeholder; fail-closed safe fallback.",
            )

        scenario = context.scenario
        orig_payment = scenario.event.payment if (scenario.event and scenario.event.payment) else None
        payment_id = orig_payment.id if orig_payment else f"pay_sim_{scenario.scenario_id}"
        amount_paise = orig_payment.amount if orig_payment else 0
        customer_email = scenario.customer.email if scenario.customer else "user@example.com"
        customer_contact = scenario.customer.contact if scenario.customer else "+919876543210"

        # Dispatch real API interaction
        if action_type in (SimulatedActionType.PAYMENT_LINK, SimulatedActionType.REMINDER):
            link_res = await self.create_payment_link(
                payment_id=payment_id,
                amount_paise=amount_paise,
                customer_details={
                    "email": customer_email,
                    "contact": customer_contact,
                },
            )
            cost_paise = 20 if action_type == SimulatedActionType.PAYMENT_LINK else 50
            if link_res.get("success"):
                return ExecutionResult(
                    success=True,
                    action_type=action_type,
                    recovered=False,  # Link created, asynchronous settlement pending
                    recovered_amount_paise=0,
                    action_cost_paise=cost_paise,
                    execution_timestamp_epoch=context.current_epoch,
                    message=f"Created Razorpay payment link {link_res.get('payment_link_id')}.",
                )
            else:
                return ExecutionResult(
                    success=False,
                    action_type=action_type,
                    recovered=False,
                    recovered_amount_paise=0,
                    action_cost_paise=0,
                    execution_timestamp_epoch=context.current_epoch,
                    message=f"Failed to create payment link: {link_res.get('error')}",
                )

        elif action_type in (SimulatedActionType.RETRY_NOW, SimulatedActionType.RETRY_LATER):
            # Check status of payment on gateway
            payment_entity = await self.fetch_payment_status(payment_id)
            cost_paise = 20
            if payment_entity:
                is_captured = payment_entity.status == PaymentState.CAPTURED
                return ExecutionResult(
                    success=True,
                    action_type=action_type,
                    recovered=is_captured,
                    recovered_amount_paise=amount_paise if is_captured else 0,
                    action_cost_paise=cost_paise,
                    execution_timestamp_epoch=context.current_epoch,
                    message=f"Executed payment status inspection for {payment_id}. State: {payment_entity.status}",
                )
            else:
                return ExecutionResult(
                    success=False,
                    action_type=action_type,
                    recovered=False,
                    recovered_amount_paise=0,
                    action_cost_paise=cost_paise,
                    execution_timestamp_epoch=context.current_epoch,
                    message=f"Razorpay retry/inquiry failed for payment {payment_id}.",
                )

        return ExecutionResult(
            success=False,
            action_type=action_type,
            recovered=False,
            recovered_amount_paise=0,
            action_cost_paise=0,
            execution_timestamp_epoch=context.current_epoch,
            message=f"Unhandled action type {action_type}.",
        )
