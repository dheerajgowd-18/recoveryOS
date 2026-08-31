# RecoveryOS Security Architecture & Threat Model

This document outlines the threat analysis, attack surface, failure modes, mitigations, and residual risks for the RecoveryOS autonomous revenue recovery agent.

---

## 1. System Attack Surface & Threat Matrix

| ID | Threat Category | Potential Impact | Architecture Mitigation | Residual Risk |
| :--- | :--- | :--- | :--- | :--- |
| **T-01** | **Unauthorized Action Execution** | Rogue policy triggers unverified money movements or link dispatches | Pre-execution `ToolFirewall` validation gate rejects any action not explicitly whitelisted in `SimulatedActionType` | Zero; unvalidated action types raise `SchemaValidationError` and halt loop |
| **T-02** | **Malformed Action Schema** | Missing parameters or malformed payloads crash downstream payment adapters | Strict Pydantic v2 domain schemas (`extra="forbid"`) validate all parameters prior to dispatch | Low; schema mismatch immediately caught before executor invocation |
| **T-03** | **Stale State Execution** | Customer pays organically out-of-band; agent executes duplicate charge or link | Stale Action Protection re-inspects `PaymentAggregate` terminal state immediately prior to executor dispatch; cancels pending retry | Minimal; edge case if webhook is delayed beyond gateway settlement window |
| **T-04** | **Duplicate Webhook Replay** | Replayed webhook triggers duplicate reconciliation and dunning loops | `IdempotencyTracker` derives deterministic keys (`evt_{account}_{id}_{event}_{epoch}`) and caches execution receipts | Zero in-memory; requires distributed Redis locks in multi-instance production |
| **T-05** | **Out-of-Order Events** | Late `payment.authorized` arrives after `payment.captured`, causing state reversion | `StateReconciler` orders timelines by `occurred_at` and enforces terminal state preservation (`CAPTURED` is irreversible) | Zero; invalid backward transitions raise `InvalidStateTransitionError` |
| **T-06** | **Policy Service Outage** | Policy engine crashes, times out, or throws unexpected exceptions | Fail-Closed Architecture: `AgentRuntime` catches `PolicyOutageError`, records `NO_ACTION`, and safely halts with `stop_reason="POLICY_OUTAGE"` | Minimal; delayed recovery cycle until policy service health restores |
| **T-07** | **Executor Timeout / Network Drop** | Payment gateway API drops connection during execution | `AgentRuntime` wraps executor calls in `try/except (TimeoutError, ConnectionError)`, logs failure, and cleanly exits without crashing | Unconfirmed transactions require background reconciliation polling |
| **T-08** | **Customer Opt-Out Violation** | Unsolicited SMS/WhatsApp messages sent to opted-out customers | `ToolFirewall` checks `CustomerConsentContext`; raises `ConsentViolationError` and blocks customer-facing actions | Dependent on external CRM/portal webhook sync latency |
| **T-09** | **Contact Fatigue & Harassment** | Aggressive dunning spams customer, driving brand damage and churn | Physical failure constraints filter useless actions (e.g. retries on expired cards); Expected-Value scorer favors timed retries | Modeling priors must be tuned per merchant communication policy |
| **T-10** | **Hidden Outcome / Archetype Leakage** | Policy exploits latent counterfactual outcomes to artificially win benchmarks | `PublicScenarioView` isolates only observable error codes and amounts; hidden outcomes are sequestered in `EvaluationHarness` | Zero; strictly verified by unit boundary tests |
| **T-11** | **PII Exposure in Audit Logs** | Sensitive card numbers, phone numbers, or emails leak into log files | Public view projects masked identifiers; raw payment entities remain inside encrypted domain storage | Access controls must govern access to `DecisionLogStore` |
| **T-12** | **Secret / API Key Exposure** | HMAC secrets or gateway credentials leak into logs or client code | Webhook HMAC validation uses raw request bytes with constant-time `hmac.compare_digest`; secrets read from environment variables | Standard secret management (Vault/AWS Secrets Manager) required in prod |
| **T-13** | **Runaway Retry Loops** | Endless retry loops incur excessive gateway penalty fees | Hard bounded loop (`max_iterations = 5`) and attempt caps enforce early stopping (`POLICY_ABSTAINED`) | Zero; bounded loop halts deterministically |
| **T-14** | **Prompt Manipulation / Injection (Future LLM)** | Adversarial customer prompt coerces LLM into waiving fees or issuing refunds | LLMs are restricted to advisory diagnosis; all execution passes through deterministic `ToolFirewall` gates | Zero direct execution; firewall enforces policy invariants unconditionally |

---

## 2. Fail-Closed Architectural Governance

RecoveryOS enforces a strict **Fail-Closed Governance Standard**:
1. **No Autonomous Action Without Explicit Validation**: An action proposed by any policy (heuristic, ML, or future LLM) is treated as untrusted input until verified by the `ToolFirewall`.
2. **Safety Invariants Over Automation**: When internal components experience outages, network drops, or ambiguity, the system defaults to `NO_ACTION` and alerts operators rather than risking unauthorized financial side-effects.
