"""Public scenario view projection strictly sanitizing private simulator attributes."""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import FailureClass
from simulator.generator import SimulatedScenario


class PublicScenarioView(BaseModel):
    """Sanitized, public view of a recovery scenario safe for policy ingestion.

    Strictly excludes:
    - `hidden_outcomes` / `potential_outcomes` (Secret counterfactuals)
    - `archetype` / `customer_archetype` (Latent behavioral ground truths)
    - Any internal simulator ground-truth states
    """
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., description="Unique scenario identifier")
    failure_class: FailureClass = Field(..., description="Observable root cause classification")
    failure_code: Optional[str] = Field(default=None, description="Public gateway error code")
    error_description: Optional[str] = Field(default=None, description="Public error message")
    error_source: Optional[str] = Field(default=None, description="Error source (e.g. gateway, issuer)")
    error_step: Optional[str] = Field(default=None, description="Failed payment step")
    error_reason: Optional[str] = Field(default=None, description="Failure reason")
    amount_in_paise: int = Field(..., ge=100, description="Transaction amount in smallest currency unit")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    attempt_count: int = Field(default=1, ge=1, description="Current dunning attempt count")
    customer_id: Optional[str] = Field(default=None, description="Anonymized customer identifier")
    payment_id: Optional[str] = Field(default=None, description="Payment transaction identifier")
    payment_method: Optional[str] = Field(default="card", description="Payment instrument type")

    @classmethod
    def from_simulated_scenario(cls, scenario: SimulatedScenario) -> "PublicScenarioView":
        """Extract only public domain event fields, strictly discarding secret simulation attributes."""
        payment = scenario.event.payment
        attempt = 1
        if payment and payment.description and "Attempt " in payment.description:
            try:
                attempt = int(payment.description.split("Attempt ")[1].split()[0])
            except (IndexError, ValueError):
                attempt = 1

        return cls(
            scenario_id=scenario.scenario_id,
            failure_class=scenario.failure_class,
            failure_code=payment.error_code if payment else None,
            error_description=payment.error_description if payment else None,
            error_source=payment.error_source if payment else None,
            error_step=payment.error_step if payment else None,
            error_reason=payment.error_reason if payment else None,
            amount_in_paise=payment.amount if payment else 0,
            currency=payment.currency if payment else "INR",
            attempt_count=attempt,
            customer_id=payment.customer_id if payment else None,
            payment_id=payment.id if payment else None,
            payment_method=payment.method if payment else "card",
        )
