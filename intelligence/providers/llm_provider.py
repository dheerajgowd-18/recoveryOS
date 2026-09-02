"""Production-grade LLM-compatible diagnosis provider boundary with strict schema validation, timeout, retries, and deterministic fallback."""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
import httpx
from pydantic import ValidationError

from intelligence.context import ObservableRecoveryContext
from intelligence.providers.base import BaseDiagnosisProvider
from intelligence.providers.deterministic import DeterministicDiagnosisProvider
from intelligence.schemas import DiagnosisLabel, StructuredDiagnosis
from simulator.config import SimulatedActionType

logger = logging.getLogger("recoveryos.intelligence.llm")

DEFAULT_SYSTEM_PROMPT = """You are the RecoveryOS Diagnostic Intelligence Engine for autonomous payment recovery.
Your job is to analyze the observable transaction failure context and produce a structured root cause diagnosis.

STRICT OPERATIONAL RULES:
1. Base your diagnosis strictly on the provided observable fields (error codes, descriptions, timing, attempt counts).
2. Choose diagnosis_label from ONLY these canonical values:
   - "transient_gateway_failure"
   - "insufficient_funds"
   - "expired_payment_method"
   - "authentication_failure"
   - "mandate_issue"
   - "customer_abandonment"
   - "subscription_payment_failure"
   - "overdue_invoice"
   - "unknown_failure"
3. Choose recommended_candidate_actions from ONLY these allowed action types:
   - "no_action"
   - "retry_now"
   - "retry_later"
   - "payment_link"
   - "reminder"
4. Output MUST be a single, valid JSON object matching the requested schema. Do not include markdown codeblocks or preamble outside the JSON.

REQUIRED JSON SCHEMA:
{
  "diagnosis_label": "transient_gateway_failure",
  "confidence": 0.85,
  "evidence_codes": ["OBS_GATEWAY_ERROR", "OBS_NETWORK_TIMEOUT"],
  "uncertainties": [],
  "recommended_candidate_actions": ["retry_later", "retry_now"],
  "recommended_timing_hint": "delay_2h",
  "human_review_required": false,
  "abstain_recommended": false,
  "rationale": "Clear, concise diagnostic explanation"
}
"""


class LLMDiagnosisProvider(BaseDiagnosisProvider):
    """Production-grade configurable LLM diagnosis provider with strict schema validation, retry, timeout, and safe deterministic fallback.

    Guarantees:
    - Never requires external API keys for default test / demo execution.
    - If unconfigured, timed out, malformed, or unreachable, automatically falls back to DeterministicDiagnosisProvider.
    - Marks fallback provenance with `diagnosis_source = 'deterministic_fallback'`.
    - Differentiates failure modes: LLM_REASONING, NO_API_KEY, TIMEOUT, MALFORMED_OUTPUT, API_ERROR.
    - Comprehensive telemetry tracking: latency, tokens, total calls, successes, fallbacks, malformed count.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        timeout_seconds: float = 3.0,
        max_retries: int = 1,
        fallback_provider: Optional[DeterministicDiagnosisProvider] = None,
        client: Optional[Any] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("RAZORPAY_AI_LLM_KEY") or os.getenv("GROQ_API_KEY")
        self.model_name = model_name or os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.fallback_provider = fallback_provider or DeterministicDiagnosisProvider()
        self._client = client
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

        # Operational telemetry counters
        self.total_invocations: int = 0
        self.llm_calls: int = 0
        self.llm_successes: int = 0
        self.fallback_count: int = 0
        self.invalid_output_count: int = 0
        self.timeout_count: int = 0
        self.last_latency_ms: float = 0.0
        self.total_latency_ms: float = 0.0
        self.prompt_tokens_total: int = 0
        self.completion_tokens_total: int = 0

    @property
    def average_latency_ms(self) -> float:
        """Average latency in ms across successful LLM calls."""
        return (self.total_latency_ms / self.llm_successes) if self.llm_successes > 0 else 0.0

    @property
    def fallback_rate(self) -> float:
        """Fraction of total invocations that fell back to deterministic rules."""
        return (self.fallback_count / self.total_invocations) if self.total_invocations > 0 else 0.0

    def build_user_prompt(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[Any] = None,
    ) -> str:
        """Constructs sanitized prompt containing observable context features and bounded recovery memory with provenance."""
        obs_payload = context.model_dump(exclude_none=True)
        
        prompt_parts = [
            "Analyze the following observable transaction failure context and retrieved bounded recovery memory.",
            "Return the structured root cause diagnosis JSON according to the required schema.",
            "",
            "=== OBSERVABLE TRANSACTION CONTEXT ===",
            json.dumps(obs_payload, indent=2),
        ]

        if memory_bundle is not None:
            prompt_parts.extend([
                "",
                "=== BOUNDED RECOVERY MEMORY (RETRIEVED WITH PROVENANCE) ===",
            ])
            if hasattr(memory_bundle, "retrieved_items"):
                for idx, item in enumerate(memory_bundle.retrieved_items, start=1):
                    item_dict = {
                        "item_id": getattr(item, "item_id", f"mem_{idx}"),
                        "category": getattr(getattr(item, "category", None), "value", str(getattr(item, "category", "general"))),
                        "title": getattr(item, "title", ""),
                        "content": getattr(item, "content", {}),
                        "provenance": getattr(item, "provenance", {}).model_dump() if hasattr(getattr(item, "provenance", None), "model_dump") else getattr(item, "provenance", {}),
                    }
                    prompt_parts.append(f"--- Memory Item {idx}: {item_dict['title']} ---")
                    prompt_parts.append(json.dumps(item_dict, indent=2))
            elif isinstance(memory_bundle, dict):
                prompt_parts.append(json.dumps(memory_bundle, indent=2))

        prompt_parts.extend([
            "",
            "CRITICAL INSTRUCTIONS: Ground your diagnosis strictly in the observable evidence and retrieved memory above.",
            "Do not invent unobserved facts. If evidence is ambiguous, set confidence lower and list uncertainties.",
        ])

        return "\n".join(prompt_parts)

    def parse_and_validate_response(self, raw_json_or_dict: object) -> StructuredDiagnosis:
        """Strictly validate and parse LLM-generated output into StructuredDiagnosis."""
        try:
            if isinstance(raw_json_or_dict, str):
                cleaned = raw_json_or_dict.strip()
                # Handle potential markdown code fencing if LLM wraps in ```json ... ```
                if cleaned.startswith("```"):
                    lines = cleaned.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    cleaned = "\n".join(lines).strip()
                data = json.loads(cleaned)
            elif isinstance(raw_json_or_dict, dict):
                data = dict(raw_json_or_dict)
            else:
                raise ValueError(f"Invalid input type: {type(raw_json_or_dict).__name__}")

            if not isinstance(data, dict):
                raise ValueError(f"Expected JSON object dictionary, got {type(data).__name__}")

            # Ensure diagnosis_source is properly attributed
            data["diagnosis_source"] = "llm_structured"
            if not data.get("model_version"):
                data["model_version"] = self.model_name

            # Normalize candidate actions if present
            if "recommended_candidate_actions" in data and isinstance(data["recommended_candidate_actions"], list):
                actions = []
                for a in data["recommended_candidate_actions"]:
                    actions.append(SimulatedActionType(str(a).lower().strip()))
                data["recommended_candidate_actions"] = actions

            diagnosis = StructuredDiagnosis(**data)
            return diagnosis
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as e:
            self.invalid_output_count += 1
            raise ValueError(f"LLM output validation error: {str(e)}") from e

    def _execute_http_completion(self, user_prompt: str) -> Dict[str, Any]:
        """Synchronously execute chat completion HTTP request against OpenAI-compatible endpoint."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"LLM API returned HTTP {resp.status_code}: {resp.text}",
                    request=resp.request,
                    response=resp,
                )
            return resp.json()

    async def _execute_http_completion_async(self, user_prompt: str) -> Dict[str, Any]:
        """Asynchronously execute chat completion HTTP request against OpenAI-compatible endpoint."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"LLM API returned HTTP {resp.status_code}: {resp.text}",
                    request=resp.request,
                    response=resp,
                )
            return resp.json()

    def _extract_content_from_response(self, response_data: Dict[str, Any]) -> str:
        """Extracts text content and tracks token usage from response dict."""
        usage = response_data.get("usage", {})
        if usage:
            self.prompt_tokens_total += usage.get("prompt_tokens", 0)
            self.completion_tokens_total += usage.get("completion_tokens", 0)

        choices = response_data.get("choices", [])
        if not choices:
            raise ValueError("No choices in LLM API response")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise ValueError("Empty message content in LLM API response")
        return content

    def _wrap_fallback(self, fallback_diag: StructuredDiagnosis, reason_code: str) -> StructuredDiagnosis:
        """Wraps fallback diagnosis with deterministic fallback provenance."""
        return StructuredDiagnosis(
            diagnosis_label=fallback_diag.diagnosis_label,
            confidence=fallback_diag.confidence,
            evidence_codes=fallback_diag.evidence_codes + [reason_code],
            uncertainties=fallback_diag.uncertainties,
            recommended_candidate_actions=fallback_diag.recommended_candidate_actions,
            recommended_timing_hint=fallback_diag.recommended_timing_hint,
            human_review_required=fallback_diag.human_review_required,
            abstain_recommended=fallback_diag.abstain_recommended,
            rationale=f"[Deterministic Fallback] {fallback_diag.rationale}",
            diagnosis_source="deterministic_fallback",
            model_version=f"rules-fallback-{fallback_diag.model_version or 'v1.0'}",
        )

    def diagnose_sync(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[Any] = None,
    ) -> StructuredDiagnosis:
        """Produce structured diagnosis synchronously with robust error handling and fallback."""
        self.total_invocations += 1
        start_time = time.perf_counter()

        # Check API key configuration
        if not self.api_key and self._client is None:
            self.fallback_count += 1
            fallback_diag = self.fallback_provider.diagnose_sync(context, memory_bundle)
            return self._wrap_fallback(fallback_diag, "FALLBACK_NO_API_KEY")

        self.llm_calls += 1
        user_prompt = self.build_user_prompt(context, memory_bundle)

        # Execute with retries for transient errors
        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                if self._client is not None:
                    # Injected mock/custom client support
                    if hasattr(self._client, "chat") and hasattr(self._client.chat, "completions"):
                        chat_completion = self._client.chat.completions.create(
                            messages=[
                                {"role": "system", "content": self.system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            model=self.model_name,
                            response_format={"type": "json_object"},
                            temperature=0.1,
                        )
                        raw_content = chat_completion.choices[0].message.content
                    else:
                        raise ValueError("Injected client does not adhere to chat.completions protocol")
                else:
                    response_json = self._execute_http_completion(user_prompt)
                    raw_content = self._extract_content_from_response(response_json)

                diagnosis = self.parse_and_validate_response(raw_content)

                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                self.llm_successes += 1
                self.last_latency_ms = elapsed_ms
                self.total_latency_ms += elapsed_ms
                return diagnosis

            except (TimeoutError, httpx.TimeoutException) as e:
                self.timeout_count += 1
                last_exception = e
            except Exception as e:
                last_exception = e

        # All attempts failed -> fallback
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        self.last_latency_ms = elapsed_ms
        self.fallback_count += 1

        is_timeout = isinstance(last_exception, (TimeoutError, httpx.TimeoutException)) or (
            last_exception and "timeout" in type(last_exception).__name__.lower()
        )
        is_malformed = isinstance(last_exception, ValueError) and "validation error" in str(last_exception).lower()

        if is_timeout:
            reason_code = "FALLBACK_TIMEOUT"
        elif is_malformed:
            reason_code = "FALLBACK_MALFORMED_OUTPUT"
        else:
            reason_code = "FALLBACK_API_ERROR"

        logger.warning(
            f"LLM diagnosis failed ({type(last_exception).__name__}: {last_exception}); fallback code: {reason_code}"
        )
        fallback_diag = self.fallback_provider.diagnose_sync(context, memory_bundle)
        return self._wrap_fallback(fallback_diag, reason_code)

    async def diagnose(
        self,
        context: ObservableRecoveryContext,
        memory_bundle: Optional[Any] = None,
    ) -> StructuredDiagnosis:
        """Produce structured diagnosis asynchronously with robust error handling and fallback."""
        self.total_invocations += 1
        start_time = time.perf_counter()

        if not self.api_key and self._client is None:
            self.fallback_count += 1
            fallback_diag = self.fallback_provider.diagnose_sync(context, memory_bundle)
            return self._wrap_fallback(fallback_diag, "FALLBACK_NO_API_KEY")

        self.llm_calls += 1
        user_prompt = self.build_user_prompt(context, memory_bundle)

        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                if self._client is not None:
                    # Injected client execution
                    if hasattr(self._client, "chat") and hasattr(self._client.chat, "completions"):
                        chat_completion = self._client.chat.completions.create(
                            messages=[
                                {"role": "system", "content": self.system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            model=self.model_name,
                            response_format={"type": "json_object"},
                            temperature=0.1,
                        )
                        raw_content = chat_completion.choices[0].message.content
                    else:
                        raise ValueError("Injected client does not adhere to chat.completions protocol")
                else:
                    response_json = await self._execute_http_completion_async(user_prompt)
                    raw_content = self._extract_content_from_response(response_json)

                diagnosis = self.parse_and_validate_response(raw_content)

                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                self.llm_successes += 1
                self.last_latency_ms = elapsed_ms
                self.total_latency_ms += elapsed_ms
                return diagnosis

            except (TimeoutError, httpx.TimeoutException) as e:
                self.timeout_count += 1
                last_exception = e
            except Exception as e:
                last_exception = e

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        self.last_latency_ms = elapsed_ms
        self.fallback_count += 1

        is_timeout = isinstance(last_exception, (TimeoutError, httpx.TimeoutException)) or (
            last_exception and "timeout" in type(last_exception).__name__.lower()
        )
        is_malformed = isinstance(last_exception, ValueError) and "validation error" in str(last_exception).lower()

        if is_timeout:
            reason_code = "FALLBACK_TIMEOUT"
        elif is_malformed:
            reason_code = "FALLBACK_MALFORMED_OUTPUT"
        else:
            reason_code = "FALLBACK_API_ERROR"

        fallback_diag = self.fallback_provider.diagnose_sync(context)
        return self._wrap_fallback(fallback_diag, reason_code)

