"""Abstract base class defining the boundary contract for Razorpay gateway integrations."""
from abc import ABC, abstractmethod
from typing import Optional

from domain.actions import Action
from domain.events import PaymentEntity, SubscriptionEntity


class RazorpayAdapter(ABC):
    """Abstract interface for communicating with Razorpay payment services."""

    @abstractmethod
    async def fetch_payment(self, payment_id: str) -> Optional[PaymentEntity]:
        """Fetch payment details by payment ID.

        Args:
            payment_id: Razorpay payment identifier.

        Returns:
            PaymentEntity domain model if found, None otherwise.
        """
        pass

    @abstractmethod
    async def fetch_subscription(self, subscription_id: str) -> Optional[SubscriptionEntity]:
        """Fetch subscription details by subscription ID.

        Args:
            subscription_id: Razorpay subscription identifier.

        Returns:
            SubscriptionEntity domain model if found, None otherwise.
        """
        pass

    @abstractmethod
    async def retry_invoice_payment(self, invoice_id: str) -> bool:
        """Trigger an asynchronous payment retry for a pending or failed invoice.

        Args:
            invoice_id: Razorpay invoice identifier.

        Returns:
            True if retry was successfully initiated, False otherwise.
        """
        pass

    @abstractmethod
    async def pause_subscription(self, subscription_id: str) -> Optional[SubscriptionEntity]:
        """Pause an active subscription in Razorpay.

        Args:
            subscription_id: Razorpay subscription identifier.

        Returns:
            Updated SubscriptionEntity.
        """
        pass

    @abstractmethod
    async def cancel_subscription(self, subscription_id: str) -> Optional[SubscriptionEntity]:
        """Cancel an active or halted subscription in Razorpay.

        Args:
            subscription_id: Razorpay subscription identifier.

        Returns:
            Updated SubscriptionEntity.
        """
        pass

    @abstractmethod
    async def execute_action(self, action: Action) -> Action:
        """Execute a governed recovery action against the gateway or customer channel.

        Args:
            action: The Action domain object to execute.

        Returns:
            The mutated Action domain object with updated execution status.
        """
        pass
