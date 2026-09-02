"""Groq OpenAI-Compatible Diagnosis Provider defaulting to openai/gpt-oss-120b with strict schema validation, replay cache, and deterministic fallback."""
import logging
import os
from typing import Any, Dict, Optional

from intelligence.config import (
    DEFAULT_GROQ_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    default_llm_config,
)
from intelligence.context import ObservableRecoveryContext
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.providers.llm_provider import LLMDiagnosisProvider
from intelligence.schemas import StructuredDiagnosis

logger = logging.getLogger("recoveryos.intelligence.groq")

# Canonical default Groq production model for RecoveryOS Track 03
DEFAULT_GROQ_MODEL = DEFAULT_LLM_MODEL  # "openai/gpt-oss-120b"


class GroqLLMDiagnosisProvider(LLMDiagnosisProvider):
    """Production-grade LLM diagnosis provider targeted for Groq openai/gpt-oss-120b.

    Guarantees:
    - Centralized configuration defaulting to Groq's OpenAI-compatible endpoint (https://api.groq.com/openai/v1).
    - Model target: openai/gpt-oss-120b.
    - True non-blocking async execution and replay caching.
    - Seamless fallback to DeterministicDiagnosisProvider on timeout, error, or missing credentials.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
        fallback_provider: Optional[DeterministicDiagnosisProvider] = None,
        client: Optional[Any] = None,
    ) -> None:
        effective_key = api_key or os.getenv("GROQ_API_KEY") or default_llm_config.api_key
        effective_model = model_id or os.getenv("GROQ_MODEL_ID") or DEFAULT_GROQ_MODEL
        effective_base_url = base_url or os.getenv("GROQ_BASE_URL") or DEFAULT_GROQ_BASE_URL
        effective_timeout = timeout_seconds if timeout_seconds is not None else default_llm_config.timeout_seconds

        super().__init__(
            api_key=effective_key,
            model_name=effective_model,
            base_url=effective_base_url,
            timeout_seconds=effective_timeout,
            max_retries=max_retries,
            fallback_provider=fallback_provider,
            client=client,
        )
        self.model_id = effective_model

    def _get_client(self) -> Optional[Any]:
        """Lazy initialization of Groq client if not injected."""
        if self._client is not None:
            return self._client

        if not self.api_key:
            return None

        try:
            from groq import Groq
            self._client = Groq(api_key=self.api_key, timeout=self.timeout_seconds)
            return self._client
        except Exception as e:
            logger.warning(f"Failed to initialize Groq SDK client: {e}")
            return None
