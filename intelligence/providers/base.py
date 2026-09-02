"""Abstract Base Diagnosis Provider interface for RecoveryOS."""
from abc import ABC, abstractmethod
from typing import Optional

from intelligence.context import ObservableRecoveryContext
from intelligence.schemas import StructuredDiagnosis
from rag.schemas import BoundedContextBundle


class BaseDiagnosisProvider(ABC):
    """Abstract interface for intelligence diagnosis engines."""

    @abstractmethod
    async def diagnose(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StructuredDiagnosis:
        """Produce a structured diagnosis from observable context and bounded memory asynchronously."""
        pass

    @abstractmethod
    def diagnose_sync(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[BoundedContextBundle] = None,
    ) -> StructuredDiagnosis:
        """Produce a structured diagnosis from observable context and bounded memory synchronously."""
        pass

