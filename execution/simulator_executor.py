"""Simulation executor resolving candidate recovery actions against hidden ground-truth counterfactuals."""
from datetime import datetime, timezone
from typing import Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from domain.actions import Action
from domain.enums import ActionType, PaymentState
from domain.events import (
    PaymentContainer,
    PaymentEntity,
    PaymentEvent,
    WebhookPayload,
    WebhookPayloadContent,
)
from execution.executor import ExecutionContext, ExecutionResult, RecoveryExecutor
from governor.exceptions import PolicyOutageError
from simulator.config import SimulatedActionType


class ExecutionFaultConfig(BaseModel):
    """Failure injection parameters to test runtime fault tolerance and resilience."""
    model_config = ConfigDict(extra="forbid")

    force_timeout: bool = Field(default=False, description="Simulate a gateway timeout exception")
    force_connection_error: bool = Field(default=False, description="Simulate a network connection drop")
    force_policy_outage: bool = Field(default=False, description="Simulate a policy service outage")


class SimulatorExecutor(RecoveryExecutor):
    """Executes recovery interventions by querying scenario counterfactuals and synthesizing resulting domain events."""

    def __init__(self, fault_config: Optional[ExecutionFaultConfig] = None) -> None:
        self.fault_config = fault_config or ExecutionFaultConfig()

    def _map_domain_action(self, action: Union[SimulatedActionType, Action]) -> SimulatedActionType:
        """Map domain Action or SimulatedActionType into canonical SimulatedActionType."""
        if isinstance(action, SimulatedActionType):
            return action

        mapping = {
            ActionType.RETRY_PAYMENT: (
                SimulatedActionType.RETRY_LATER
                if (action.parameters and action.parameters.retry_delay_seconds and action.parameters.retry_delay_seconds > 0)
                else SimulatedActionType.RETRY_NOW
            ),
            ActionType.SEND_DUNNING_EMAIL: SimulatedActionType.PAYMENT_LINK,
            ActionType.SEND_WHATSAPP_REMINDER: SimulatedActionType.REMINDER,
            ActionType.PAUSE_SUBSCRIPTION: SimulatedActionType.NO_ACTION,
            ActionType.CANCEL_SUBSCRIPTION: SimulatedActionType.NO_ACTION,
            ActionType.OFFER_DISCOUNT: SimulatedActionType.PAYMENT_LINK,
        }
        return mapping.get(action.action_type, SimulatedActionType.NO_ACTION)

    async def execute(
        self,
        action: Union[SimulatedActionType, Action],
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Resolve the action against hidden potential outcomes and synthesize the resulting Razorpay domain event.

        Raises:
            TimeoutError: If fault injection config specifies force_timeout.
            ConnectionError: If fault injection config specifies force_connection_error.
            PolicyOutageError: If fault injection config specifies force_policy_outage.
        """
        # Failure Injection Checks
        if self.fault_config.force_timeout:
            raise TimeoutError("Simulated payment gateway timeout during action execution.")

        if self.fault_config.force_connection_error:
            raise ConnectionError("Simulated network connection drop during action dispatch.")

        if self.fault_config.force_policy_outage:
            raise PolicyOutageError("Simulated policy engine service outage.")

        action_type = self._map_domain_action(action)
        scenario = context.scenario
        outcome = scenario.hidden_outcomes.get_outcome(action_type)

        execution_epoch = context.current_epoch
        occurred_at = datetime.fromtimestamp(execution_epoch, tz=timezone.utc).replace(tzinfo=None)

        orig_payment = scenario.event.payment
        payment_id = orig_payment.id if orig_payment else f"pay_sim_{scenario.scenario_id}"
        order_id = orig_payment.order_id if orig_payment else f"order_sim_{scenario.scenario_id}"
        invoice_id = orig_payment.invoice_id if orig_payment else f"inv_sim_{scenario.scenario_id}"
        customer_id = orig_payment.customer_id if orig_payment else scenario.customer.customer_id
        amount = orig_payment.amount if orig_payment else 0
        currency = orig_payment.currency if orig_payment else "INR"
        merchant_account_id = scenario.event.account_id

        if outcome.recovered:
            # Generate payment.captured event
            payment_entity = PaymentEntity(
                id=payment_id,
                entity="payment",
                amount=amount,
                currency=currency,
                status=PaymentState.CAPTURED,
                order_id=order_id,
                invoice_id=invoice_id,
                international=False,
                method=orig_payment.method if orig_payment else "card",
                amount_refunded=0,
                refund_status=None,
                captured=True,
                description=f"Subscription Recovery Simulation - Attempt {context.attempt_count} (Recovered)",
                card_id=orig_payment.card_id if orig_payment else None,
                bank=orig_payment.bank if orig_payment else None,
                wallet=orig_payment.wallet if orig_payment else None,
                vpa=orig_payment.vpa if orig_payment else None,
                email=scenario.customer.email,
                contact=scenario.customer.contact,
                customer_id=customer_id,
                error_code=None,
                error_description=None,
                error_source=None,
                error_step=None,
                error_reason=None,
                error=None,
                created_at=execution_epoch,
            )

            event_type = "payment.captured"
            webhook_payload = WebhookPayload(
                entity="event",
                account_id=merchant_account_id,
                event=event_type,
                contains=["payment"],
                payload=WebhookPayloadContent(
                    payment=PaymentContainer(entity=payment_entity)
                ),
                created_at=execution_epoch,
            )

            event_id = f"evt_{merchant_account_id}_{payment_id}_{event_type}_{execution_epoch}"
            payment_event = PaymentEvent(
                event_id=event_id,
                event_type=event_type,
                account_id=merchant_account_id,
                occurred_at=occurred_at,
                payment=payment_entity,
                subscription=None,
            )

            return ExecutionResult(
                success=True,
                action_type=action_type,
                resulting_event=payment_event,
                resulting_payload=webhook_payload,
                recovered=True,
                recovered_amount_paise=outcome.recovered_amount_paise,
                action_cost_paise=outcome.action_cost_paise,
                execution_timestamp_epoch=execution_epoch,
                message=f"Action {action_type.value} succeeded; payment {payment_id} transitioned to CAPTURED.",
            )

        else:
            # Generate next payment.failed event with incremented attempt count
            next_attempt = context.attempt_count + 1
            payment_entity = PaymentEntity(
                id=payment_id,
                entity="payment",
                amount=amount,
                currency=currency,
                status=PaymentState.FAILED,
                order_id=order_id,
                invoice_id=invoice_id,
                international=False,
                method=orig_payment.method if orig_payment else "card",
                amount_refunded=0,
                refund_status=None,
                captured=False,
                description=f"Subscription Recovery Simulation - Attempt {next_attempt}",
                card_id=orig_payment.card_id if orig_payment else None,
                bank=orig_payment.bank if orig_payment else None,
                wallet=orig_payment.wallet if orig_payment else None,
                vpa=orig_payment.vpa if orig_payment else None,
                email=scenario.customer.email,
                contact=scenario.customer.contact,
                customer_id=customer_id,
                error_code=orig_payment.error_code if orig_payment else "GATEWAY_ERROR",
                error_description=orig_payment.error_description if orig_payment else "Payment attempt failed",
                error_source=orig_payment.error_source if orig_payment else "gateway",
                error_step=orig_payment.error_step if orig_payment else "payment_authorization",
                error_reason=orig_payment.error_reason if orig_payment else "gateway_error",
                error=orig_payment.error if orig_payment else None,
                created_at=execution_epoch,
            )

            event_type = "payment.failed"
            webhook_payload = WebhookPayload(
                entity="event",
                account_id=merchant_account_id,
                event=event_type,
                contains=["payment"],
                payload=WebhookPayloadContent(
                    payment=PaymentContainer(entity=payment_entity)
                ),
                created_at=execution_epoch,
            )

            event_id = f"evt_{merchant_account_id}_{payment_id}_{event_type}_{execution_epoch}"
            payment_event = PaymentEvent(
                event_id=event_id,
                event_type=event_type,
                account_id=merchant_account_id,
                occurred_at=occurred_at,
                payment=payment_entity,
                subscription=None,
            )

            return ExecutionResult(
                success=True,
                action_type=action_type,
                resulting_event=payment_event,
                resulting_payload=webhook_payload,
                recovered=False,
                recovered_amount_paise=0,
                action_cost_paise=outcome.action_cost_paise,
                execution_timestamp_epoch=execution_epoch,
                message=f"Action {action_type.value} failed to recover; payment {payment_id} remains in FAILED state.",
            )
