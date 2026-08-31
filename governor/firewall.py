"""Tool Firewall enforcing strict action schema validation, customer consent, and idempotency safeguards."""
from typing import Dict, List, Optional, Set, Union
from pydantic import BaseModel, ConfigDict, Field

from domain.actions import Action
from domain.enums import ActionType
from governor.exceptions import (
    ConsentViolationError,
    DuplicateExecutionError,
    PolicyOutageError,
    SchemaValidationError,
)
from simulator.config import SimulatedActionType


class CustomerConsentContext(BaseModel):
    """Customer consent profile and channel opt-out preferences."""
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(..., description="Customer identifier")
    opted_out_channels: List[str] = Field(default_factory=list, description="Specific channels opted out (email, sms, whatsapp)")
    is_globally_opted_out: bool = Field(default=False, description="Whether customer has globally opted out of all recovery contact")


class ToolFirewall:
    """Strict tool validation firewall ensuring all candidate interventions satisfy schema, consent, and safety rules."""

    def __init__(self) -> None:
        self._dispatched_keys: Set[str] = set()

    def validate_action_schema(
        self,
        action: Union[SimulatedActionType, Action, Dict[str, Union[str, int, float, bool, None]]],
    ) -> SimulatedActionType:
        """Validate and parse raw or model actions into a recognized SimulatedActionType.

        Raises:
            SchemaValidationError: If the action is malformed, unrecognized, or contains invalid parameters.
        """
        if isinstance(action, SimulatedActionType):
            return action

        if isinstance(action, Action):
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
            if action.action_type not in mapping:
                raise SchemaValidationError(f"Unrecognized ActionType in Action domain model: {action.action_type}")
            return mapping[action.action_type]

        if isinstance(action, dict):
            # Parse raw dictionary (e.g. proposed by external tool or LLM)
            action_raw = action.get("action_type") or action.get("name") or action.get("action")
            if not action_raw or not isinstance(action_raw, str):
                raise SchemaValidationError(f"Missing or invalid 'action_type' in action payload: {action}")

            try:
                # Direct match against SimulatedActionType enum values
                return SimulatedActionType(action_raw.lower())
            except ValueError:
                # Check domain ActionType enum values
                try:
                    domain_type = ActionType(action_raw.lower())
                    dummy_action = Action(
                        action_id="firewall_tmp",
                        action_type=domain_type,
                        target_id="target_tmp",
                    )
                    return self.validate_action_schema(dummy_action)
                except ValueError:
                    raise SchemaValidationError(
                        f"Action '{action_raw}' does not exist in the allowed action catalogue: "
                        f"{[a.value for a in SimulatedActionType]}"
                    )

        raise SchemaValidationError(f"Unsupported action payload type: {type(action).__name__}")

    def check_consent(
        self,
        action_type: SimulatedActionType,
        consent: Optional[CustomerConsentContext] = None,
    ) -> bool:
        """Verify customer communication consent before dispatching customer-facing actions.

        Raises:
            ConsentViolationError: If customer has opted out of communications.
        """
        if consent is None:
            return True

        if action_type in (SimulatedActionType.PAYMENT_LINK, SimulatedActionType.REMINDER):
            if consent.is_globally_opted_out:
                raise ConsentViolationError(
                    f"Customer '{consent.customer_id}' has globally opted out of all dunning communications. "
                    f"Action '{action_type.value}' is blocked."
                )

            if "all" in consent.opted_out_channels:
                raise ConsentViolationError(
                    f"Customer '{consent.customer_id}' has opted out of all communication channels. "
                    f"Action '{action_type.value}' is blocked."
                )

            if action_type == SimulatedActionType.PAYMENT_LINK and "email" in consent.opted_out_channels:
                raise ConsentViolationError(
                    f"Customer '{consent.customer_id}' has opted out of email. "
                    f"Action '{action_type.value}' is blocked."
                )

            if action_type == SimulatedActionType.REMINDER and any(
                c in consent.opted_out_channels for c in ("sms", "whatsapp")
            ):
                raise ConsentViolationError(
                    f"Customer '{consent.customer_id}' has opted out of SMS/WhatsApp notifications. "
                    f"Action '{action_type.value}' is blocked."
                )

        return True

    def check_idempotency(self, execution_key: str) -> bool:
        """Enforce strict execution key idempotency to prevent duplicate action side-effects.

        Raises:
            DuplicateExecutionError: If the execution key has already been dispatched.
        """
        if execution_key in self._dispatched_keys:
            raise DuplicateExecutionError(
                f"Action with execution key '{execution_key}' was already dispatched. Duplicate blocked."
            )
        self._dispatched_keys.add(execution_key)
        return True

    def validate_and_gate(
        self,
        action: Union[SimulatedActionType, Action, Dict[str, Union[str, int, float, bool, None]]],
        execution_key: Optional[str] = None,
        consent: Optional[CustomerConsentContext] = None,
        policy_healthy: bool = True,
    ) -> SimulatedActionType:
        """Comprehensive gate verifying policy health, action schema, customer consent, and idempotency.

        Returns:
            Validated SimulatedActionType.

        Raises:
            PolicyOutageError: If policy health is degraded (fails closed).
            SchemaValidationError: If action schema is malformed.
            ConsentViolationError: If customer has opted out.
            DuplicateExecutionError: If execution key is duplicated.
        """
        if not policy_healthy:
            raise PolicyOutageError("Policy decision service is currently unavailable. Failing closed.")

        validated_action = self.validate_action_schema(action)
        self.check_consent(validated_action, consent)

        if execution_key and validated_action != SimulatedActionType.NO_ACTION:
            self.check_idempotency(execution_key)

        return validated_action
