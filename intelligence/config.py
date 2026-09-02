"""Authoritative LLM and Intelligence Configuration for RecoveryOS."""
import os
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

# Canonical production defaults for RecoveryOS Track 03
DEFAULT_LLM_PROVIDER: str = "groq"
DEFAULT_LLM_MODEL: str = "openai/gpt-oss-120b"
DEFAULT_GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
DEFAULT_TIMEOUT_SECONDS: float = 3.0
DEFAULT_MAX_RETRIES: int = 1
PROMPT_VERSION: str = "2.0.0"
DIAGNOSIS_PROMPT_VERSION: str = "2.0.0"
STRATEGY_PROMPT_VERSION: str = "1.0.0"


class LLMConfig(BaseModel):
    """Centralized configuration source for LLM providers across RecoveryOS."""
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default=DEFAULT_LLM_PROVIDER, description="Active LLM provider (default: groq)")
    model: str = Field(default=DEFAULT_LLM_MODEL, description="Canonical model identifier (default: openai/gpt-oss-120b)")
    base_url: str = Field(default=DEFAULT_GROQ_BASE_URL, description="Base API endpoint URL")
    api_key: Optional[str] = Field(default=None, description="API secret key")
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, ge=0.5, le=30.0, description="HTTP timeout in seconds")
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0, le=5, description="Transient error retries")
    prompt_version: str = Field(default=PROMPT_VERSION, description="System prompt version tag")
    structured_output_mode: bool = Field(default=True, description="Enforce JSON object / schema mode")

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Loads configuration from environment variables with canonical Groq defaults."""
        api_key = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("RAZORPAY_AI_LLM_KEY")
        model = os.getenv("GROQ_MODEL_ID") or os.getenv("LLM_MODEL_NAME") or DEFAULT_LLM_MODEL
        base_url = os.getenv("GROQ_BASE_URL") or os.getenv("OPENAI_BASE_URL") or DEFAULT_GROQ_BASE_URL
        provider = os.getenv("LLM_PROVIDER", DEFAULT_LLM_PROVIDER)
        timeout_str = os.getenv("LLM_TIMEOUT_SECONDS")
        timeout = float(timeout_str) if timeout_str else DEFAULT_TIMEOUT_SECONDS

        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout,
            max_retries=DEFAULT_MAX_RETRIES,
            prompt_version=PROMPT_VERSION,
            structured_output_mode=True,
        )


# Global default configuration instance
default_llm_config = LLMConfig.from_env()
