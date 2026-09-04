from __future__ import annotations
from typing import TYPE_CHECKING, Optional
from pydantic import BaseModel, ConfigDict, Field

from domain.aggregates import PaymentAggregate
from domain.events import PaymentEvent
from simulator.generator import SimulatedScenario

if TYPE_CHECKING:
    from governor.firewall import CustomerConsentContext


class ObservableRecoveryContext(BaseModel):
    """Sanitized observable context available to the agent, intelligence layer, and recovery policy.

    Strict Architectural Invariants:
    - Strictly excludes true failure class (ground-truth root cause).
    - Strictly excludes customer archetype (latent behavioral profile).
    - Strictly excludes hidden potential outcomes vector Y(a).
    - Strictly excludes oracle labels or counterfactual probabilities.
    """
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Unique scenario or session identifier")
    payment_id: Optional[str] = Field(default=None, description="Razorpay payment transaction ID")
    customer_id: Optional[str] = Field(default=None, description="Anonymized customer identifier")
    amount_in_paise: int = Field(..., ge=0, description="Transaction amount in smallest currency unit")
    currency: str = Field(default="INR", min_length=3, max_length=3, description="ISO currency code")
    payment_method: Optional[str] = Field(default="card", description="Observed payment instrument type")
    attempt_count: int = Field(default=1, ge=1, description="Current recovery attempt index")
    error_code: Optional[str] = Field(default=None, description="Gateway or bank error code")
    failure_code: Optional[str] = Field(default=None, description="Public gateway error code alias")
    error_description: Optional[str] = Field(default=None, description="Public gateway error description")
    error_source: Optional[str] = Field(default=None, description="Error layer (e.g. gateway, bank, customer)")
    error_step: Optional[str] = Field(default=None, description="Processing step where failure was reported")
    error_reason: Optional[str] = Field(default=None, description="Specific error reason code from gateway")
    time_since_failure_seconds: int = Field(default=0, ge=0, description="Elapsed time since initial failure")
    recent_failed_attempts: int = Field(default=1, ge=0, description="Count of consecutive recent failed attempts")
    prior_successful_payments: int = Field(default=0, ge=0, description="Historical successful transactions on record")
    prior_retry_success: Optional[bool] = Field(default=None, description="Whether prior retries have succeeded for customer")
    prior_payment_link_success: Optional[bool] = Field(default=None, description="Whether prior payment links succeeded")
    average_recovery_time_seconds: Optional[int] = Field(default=None, description="Average recovery realization delay")
    contacts_in_last_24h: int = Field(default=0, ge=0, description="Direct customer notifications in last 24 hours")
    contacts_in_last_7d: int = Field(default=0, ge=0, description="Direct customer notifications in last 7 days")
    time_since_last_contact_seconds: Optional[int] = Field(default=None, description="Seconds elapsed since last contact")
    time_since_last_successful_payment_seconds: Optional[int] = Field(default=None, description="Seconds since last capture")
    subscription_id: Optional[str] = Field(default=None, description="Associated subscription identifier if recurring")
    subscription_status: Optional[str] = Field(default=None, description="Current subscription status")
    subscription_age_days: Optional[int] = Field(default=None, description="Subscription tenure in days")
    consent_opted_out: bool = Field(default=False, description="Customer global communication opt-out flag")


class ObservableContextBuilder:
    """Projector constructing sanitized ObservableRecoveryContext from domain events or simulation."""

    @staticmethod
    def build_from_simulated_scenario(scenario: SimulatedScenario) -> ObservableRecoveryContext:
        """Extract observable features from a simulated scenario without leaking latent ground truths."""
        payment = scenario.event.payment
        attempt = 1
        if payment and payment.description and "Attempt " in payment.description:
            try:
                attempt = int(payment.description.split("Attempt ")[1].split()[0])
            except (IndexError, ValueError):
                attempt = 1

        err_code = payment.error_code if payment else None

        return ObservableRecoveryContext(
            scenario_id=scenario.scenario_id,
            payment_id=payment.id if payment else None,
            customer_id=payment.customer_id if payment else (scenario.customer.customer_id if scenario.customer else None),
            amount_in_paise=payment.amount if payment else 0,
            currency=payment.currency if payment else "INR",
            payment_method=payment.method if payment else "card",
            attempt_count=attempt,
            error_code=err_code,
            failure_code=err_code,
            error_description=payment.error_description if payment else None,
            error_source=payment.error_source if payment else None,
            error_step=payment.error_step if payment else None,
            error_reason=payment.error_reason if payment else None,
            time_since_failure_seconds=0,
            recent_failed_attempts=attempt,
            prior_successful_payments=3 if attempt == 1 else 1,
            prior_retry_success=True if payment and payment.method == "card" else None,
            prior_payment_link_success=None,
            average_recovery_time_seconds=7200,
            contacts_in_last_24h=scenario.contacts_in_last_24h,
            contacts_in_last_7d=scenario.contacts_in_last_7d,
            time_since_last_contact_seconds=None,
            time_since_last_successful_payment_seconds=86400 * 30,
            subscription_id=scenario.event.subscription.id if scenario.event.subscription else None,
            subscription_status=scenario.event.subscription.status if scenario.event.subscription else None,
            subscription_age_days=90,
            consent_opted_out=False,
        )

    @staticmethod
    def build_from_payment_event(
        event: PaymentEvent,
        aggregate: Optional[PaymentAggregate] = None,
        customer_consent: Optional[CustomerConsentContext] = None,
        attempt_count: int = 1,
        scenario_id: Optional[str] = None,
    ) -> ObservableRecoveryContext:
        """Construct observable context from production/live domain event and aggregate state."""
        payment = event.payment
        payment_id = payment.id if payment else (aggregate.payment_id if aggregate else "unknown_pay")
        cust_id = payment.customer_id if payment else (aggregate.customer_id if aggregate else None)
        scen_id = scenario_id or f"ctx_{payment_id}_{attempt_count}"

        opted_out = False
        if customer_consent and customer_consent.is_globally_opted_out:
            opted_out = True

        err_code = (
            (payment.error_code if payment else None)
            or (payment.error.code if payment and payment.error else None)
            or (aggregate.error_code if aggregate else None)
        )
        err_desc = (
            (payment.error_description if payment else None)
            or (payment.error.description if payment and payment.error else None)
            or (aggregate.error_description if aggregate else None)
        )
        err_source = (
            (payment.error_source if payment else None)
            or (payment.error.source if payment and payment.error else None)
        )
        err_step = (
            (payment.error_step if payment else None)
            or (payment.error.step if payment and payment.error else None)
        )
        err_reason = (
            (payment.error_reason if payment else None)
            or (payment.error.reason if payment and payment.error else None)
        )

        return ObservableRecoveryContext(
            scenario_id=scen_id,
            payment_id=payment_id,
            customer_id=cust_id,
            amount_in_paise=payment.amount if payment else (aggregate.amount if aggregate else 0),
            currency=payment.currency if payment else (aggregate.currency if aggregate else "INR"),
            payment_method=payment.method if payment else (aggregate.method if aggregate else "card"),
            attempt_count=attempt_count,
            error_code=err_code,
            failure_code=err_code,
            error_description=err_desc,
            error_source=err_source,
            error_step=err_step,
            error_reason=err_reason,
            time_since_failure_seconds=0,
            recent_failed_attempts=attempt_count,
            prior_successful_payments=1,
            prior_retry_success=None,
            prior_payment_link_success=None,
            average_recovery_time_seconds=None,
            contacts_in_last_24h=0,
            contacts_in_last_7d=0,
            time_since_last_contact_seconds=None,
            time_since_last_successful_payment_seconds=None,
            subscription_id=event.subscription.id if event.subscription else None,
            subscription_status=event.subscription.status if event.subscription else None,
            subscription_age_days=None,
            consent_opted_out=opted_out,
        )
