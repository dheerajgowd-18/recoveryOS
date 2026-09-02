"""Abstract Base Diagnosis Provider interface for RecoveryOS."""
from abc import ABC, abstractmethod

from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis


class BaseDiagnosisProvider(ABC):
    """Abstract interface for intelligence diagnosis engines."""

    @abstractmethod
    async def diagnose(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        """Produce a structured diagnosis from observable context asynchronously."""
        pass

    @abstractmethod
    def diagnose_sync(self, context: ObservableRecoveryContext) -> StructuredDiagnosis:
        """Produce a structured diagnosis from observable context synchronously."""
        pass
