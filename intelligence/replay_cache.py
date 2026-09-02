"""Deterministic LLM Replay and Response Cache for RecoveryOS benchmarks and offline evaluation."""
import hashlib
import json
from typing import Any, Dict, Optional
from intelligence.schemas import StructuredDiagnosis, StrategyProposal


class LLMReplayCache:
    """In-memory and deterministic fingerprint cache for LLM reasoning responses.

    Enables:
    - Zero-network, bit-reproducible multi-seed benchmark evaluations.
    - Separation of LIVE_LLM, CACHED_LLM, and DETERMINISTIC_FALLBACK telemetry.
    - Zero leakage of hidden simulator variables.
    """

    def __init__(self) -> None:
        self._diagnosis_cache: Dict[str, Dict[str, Any]] = {}
        self._strategy_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def compute_fingerprint(
        model_version: str,
        prompt_version: str,
        observable_context: Dict[str, Any],
        memory_bundle: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Computes a deterministic SHA-256 hash fingerprint over sanitized observable input."""
        payload = {
            "model": model_version,
            "prompt_version": prompt_version,
            "context": observable_context,
            "memory": memory_bundle or {},
        }
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get_diagnosis(self, fingerprint: str) -> Optional[StructuredDiagnosis]:
        """Retrieves cached StructuredDiagnosis if present."""
        cached_data = self._diagnosis_cache.get(fingerprint)
        if cached_data:
            data = dict(cached_data)
            data["diagnosis_source"] = "cached_llm"
            return StructuredDiagnosis(**data)
        return None

    def set_diagnosis(self, fingerprint: str, diagnosis: StructuredDiagnosis) -> None:
        """Stores StructuredDiagnosis into cache."""
        dumped = diagnosis.model_dump()
        self._diagnosis_cache[fingerprint] = dumped

    def get_strategy(self, fingerprint: str) -> Optional[StrategyProposal]:
        """Retrieves cached StrategyProposal if present."""
        cached_data = self._strategy_cache.get(fingerprint)
        if cached_data:
            data = dict(cached_data)
            data["strategy_source"] = "cached_llm"
            return StrategyProposal(**data)
        return None

    def set_strategy(self, fingerprint: str, proposal: StrategyProposal) -> None:
        """Stores StrategyProposal into cache."""
        dumped = proposal.model_dump()
        self._strategy_cache[fingerprint] = dumped

    def clear(self) -> None:
        """Clears all cached replay records."""
        self._diagnosis_cache.clear()
        self._strategy_cache.clear()

    @property
    def size(self) -> int:
        """Total cached items count."""
        return len(self._diagnosis_cache) + len(self._strategy_cache)


# Global replay cache instance
global_llm_cache = LLMReplayCache()
