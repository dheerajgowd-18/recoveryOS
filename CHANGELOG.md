# Changelog

All notable changes to the RecoveryOS platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-31

### Added
- `Makefile` with standard developer targets: `install`, `test`, and `demo`.
- `.env.example` template with safe placeholder-only environment variables.
- Packaging sanity test suite (`tests/unit/test_packaging.py`) validating Makefile targets, environment variable safety, and `.gitignore` coverage.

### Changed
- `README.md`: Updated with `make` workflow commands alongside direct Python fallback execution.

### Note
- Prototype validated against the defined synthetic benchmark and local integration tests.

## [0.9.0] - 2026-08-31
### Added
- **Permanent Submission & Packaging Documentation**:
  - `ASSUMPTIONS.md`: Formalized all modeling assumptions, action cost parameters, zero-credential offline benchmark guarantees, and counterfactual simulation boundaries.
  - `THREAT_MODEL.md`: Comprehensive 14-point threat matrix covering unauthorized action execution, stale state, duplicate replay, policy outages, customer opt-out, PII exposure, and fail-closed mitigations.
  - `DEMO.md`: Complete interactive CLI demonstration guide with step-by-step judge walkthroughs and script explanations for all 5 signature cases.
  - `PITCH.md`: 5-minute timed panel presentation pitch script and defense Q&A guide addressing all anticipated architectural and evaluation queries.
  - `tests/unit/test_documentation.py`: Automated documentation consistency test suite verifying file presence, required keywords, and disclosure statements.
- **Submission Alignment**:
  - `README.md` & `PROJECT_EXPLANATION.md`: Updated to reflect official Track 03 naming (`Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery`), complete documentation links, and comprehensive system architecture diagrams.

## [0.8.0] - 2026-08-31
### Added
- **Audit & Decision Replay Engine (`audit/decision_log.py`, `audit/replay.py`)**:
  - `DecisionRecord` model capturing immutable decision provenance, candidate score breakdowns, risk evaluations, and explicit `aggregate_state_before` / `aggregate_state_after` transitions.
  - `DecisionLogStore` in-memory append-only audit persistence.
  - `ReplayEngine` enabling bit-level reconstruction of any historical decision cycle with selected-action score lookup and execution outcome.
- **Churn-Adjusted Evaluation Metrics & Benchmark (`evaluation/metrics.py`, `evaluation/harness.py`)**:
  - Extended `EvaluationMetrics` with `churn_penalty_paise`, `adjusted_net_recovery_paise`, `incremental_adjusted_net_recovery_paise`, `intervention_count`, `abstention_count`, and `actions_avoided_count`.
  - Configurable churn penalty proxy (`DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER = 250_000` paise / ₹2,500).
- **Signature Demonstration CLI (`scripts/demo.py`)**:
  - Standalone terminal showcase executing all 5 signature cases: Correct Abstention, Delayed Retry Economic Selection (with candidate scoring table), Stale Action Protection, Safety Block & Consent Enforcement, and 100-Scenario Batch Benchmark with Churn-Adjusted Economics.
- **Documentation Suite**:
  - `README.md`: First-screen benchmark table matching CLI demo output, architecture diagram, and quickstart instructions.
  - `ARCHITECTURE.md`: Deep-dive technical specification across all architectural layers.
  - `EVALUATION.md`: Mathematical definitions for Gross, Net, Churn Penalty, Adjusted Net, and Incremental Adjusted Net Recovery, alongside synthetic disclosure.
  - `LIMITATIONS.md`: Engineering-grade disclosure on churn penalty assumptions, synthetic priors, and continuous timing boundaries.
- **Test Suite (`tests/unit/test_audit.py`)**:
  - Added unit tests for decision record storage, non-first candidate score replay lookup, churn penalty calculation, actions avoided counter, demo script execution, and North Star benchmark assertion (89 total passing tests).

## [0.7.0] - 2026-08-31

### Added
- **Safety Governor & Tool Firewall (`governor/firewall.py`, `governor/exceptions.py`)**:
  - `ToolFirewall` enforcing action schema validation, channel-specific and global customer consent/opt-out checks, and dispatch idempotency keys.
  - Fail-closed exception hierarchy: `FirewallError`, `ActionBlockedError`, `SchemaValidationError`, `ConsentViolationError`, `DuplicateExecutionError`, `PolicyOutageError`.
- **Fault Injection in Simulator Executor (`execution/simulator_executor.py`)**:
  - `ExecutionFaultConfig` supporting controlled fault injection (`force_timeout`, `force_connection_error`, `force_policy_outage`).
- **Resilient Agent Runtime (`agent/runtime.py`)**:
  - Integrated `ToolFirewall` pre-execution gating to intercept malformed actions and customer consent violations.
  - Fail-closed handling for policy service outages (`POLICY_OUTAGE`).
  - Graceful degradation for executor gateway timeouts and network drops (`EXECUTION_FAILURE`) without runtime crashes.
- **Adversarial & Fault Injection Test Suite (`tests/adversarial/test_adversarial_scenarios.py`)**:
  - 9 unit and adversarial integration tests covering malformed action schema rejection, customer opt-out blocking, duplicate execution key prevention, policy outage fail-closed, and executor timeout/connection failure resilience (82 total tests across repository).

## [0.6.0] - 2026-08-31

### Added
- **Recovery Executor Framework (`execution/executor.py`, `execution/simulator_executor.py`)**:
  - `RecoveryExecutor` abstract interface with `ExecutionContext` and `ExecutionResult` contracts.
  - `SimulatorExecutor` mapping chosen policy actions to hidden scenario counterfactuals and synthesizing resulting `payment.captured` or `payment.failed` Razorpay domain events.
- **Deterministic Risk Detection (`agent/risk.py`)**:
  - `RiskDetector` assessing financial entity risk levels (`NONE`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) and gating non-failure scenarios.
- **Closed-Loop Agent Runtime (`agent/runtime.py`)**:
  - `AgentRuntime` orchestrating the observe-decide-execute-observe cycle connecting IngestionService, RiskDetector, DeterministicRecoveryPolicy, and SimulatorExecutor.
  - Bounded iteration control (`max_iterations = 5`), terminal state early-stopping, explicit abstention handling, and pre-execution stale action protection.
- **Integration Test Suite (`tests/integration/test_agent_loop.py`)**:
  - 4 new end-to-end integration tests validating full recovery lifecycle, low-value abstention, retry exhaustion stopping, and out-of-band stale action protection (73 total tests across repository).

## [0.5.0] - 2026-08-31

### Added
- **Public Policy Boundary (`policy/public_view.py`, `policy/base.py`)**:
  - `PublicScenarioView` model and `from_simulated_scenario()` factory projecting strictly sanitized domain event features while preventing latent customer archetype and counterfactual leakage.
  - Refactored `BasePolicy` and `PolicyDecision` contracts with machine-readable `reason_codes`, `expected_net_value_paise`, and `expected_incremental_value_paise`.
- **Deterministic RecoveryOS Policy v0 (`policy/deterministic.py`, `policy/candidates.py`, `policy/scoring.py`, `policy/config.py`)**:
  - `DeterministicRecoveryPolicy` ("RECOVERYOS_DETERMINISTIC_V0") with transparent candidate filtering, expected-value proxy calculation, and explicit abstention guards.
  - Candidate generator enforcing failure physics (e.g. blocking retries on expired cards, enforcing attempt caps).
  - `ExpectedValueScorer` computing incremental recovery uplift $\Delta Y = Y(a) - Y(\text{no\_action})$ and expected net value minus action costs.
- **Hardened Evaluation Harness Integration (`evaluation/harness.py`)**:
  - Updated `EvaluationHarness` to project `PublicScenarioView` before passing scenarios to policies, guaranteeing zero information leakage.
- **Test Suite (`tests/unit/test_deterministic_policy.py`)**:
  - 14 new unit tests covering public view isolation, factory parsing, candidate filtering, proxy scoring, abstention conditions, determinism, and full batch evaluation through `EvaluationHarness` (69 total tests across repository).

## [0.4.0] - 2026-08-31

### Added
- **Evaluation Harness & Metrics Engine (`evaluation/metrics.py`, `evaluation/harness.py`)**:
  - Pydantic v2 `EvaluationMetrics` and `ScenarioEvaluationRecord` models calculating Gross Recovery, Natural Recovery, Incremental Recovery, Net Recovery, Total Action Cost, Intervention Count/Rate, Churn, and Fatigue.
  - `EvaluationHarness` orchestrator processing batches of `SimulatedScenario` objects, applying policy decisions, and evaluating against hidden counterfactuals $Y(a)$.
  - Batch evaluation runner `evaluate_all()` supporting multi-policy comparative benchmarking against identical customer populations.
- **Baseline Policies Suite (`evaluation/policies.py`)**:
  - `BasePolicy` abstract base class and `PolicyDecision` model.
  - Baseline 0 (`NoActionPolicy`): Always abstain, measuring organic natural recovery.
  - Baseline 1 (`AlwaysRetryPolicy`): Unconditional immediate retry heuristic.
  - Baseline 2 (`StaticRulePolicy`): Heuristic branching on observable error codes and failure sources.
  - Baseline 3 (`ProbabilityOnlyPolicy`): Greedy probability maximizer selecting highest raw estimated recovery probability without cost or churn consideration.
- **Test Suite (`tests/unit/test_evaluation.py`)**:
  - 10 new unit tests covering baseline decision boundaries, Baseline 0 natural recovery equality, Baseline 1 full intervention count, evaluation determinism, empty batch safety, metric calculation formulas, and comparative consistency across all 4 baselines (55 total tests across repository).

## [0.3.0] - 2026-08-31

### Added
- **Synthetic Revenue-Recovery Environment (Simulator v1)**:
  - Configuration models (`SimulatorConfig`, `ScenarioConfig`, `FailureClass`, `CustomerArchetype`, `SimulatedActionType`) (`simulator/config.py`).
  - Behavioral archetype matrices and failure physics models (`ARCHETYPE_PROFILES`, `FAILURE_CLASS_BEHAVIORS`) (`simulator/archetypes.py`).
  - Hidden Potential Outcome Model $Y(a)$ computing counterfactual recovery, delay, churn, fatigue, and cost across all actions (`simulator/outcomes.py`).
  - Synthetic entity generator emitting strictly typed `SimulatedCustomer`, `PaymentEntity`, `WebhookPayload`, and `PaymentEvent` models (`simulator/entities.py`).
  - Batch scenario generator orchestrator with isolated PRNG seed management for 100% deterministic reproducibility (`simulator/generator.py`).
- **Test Suite**:
  - 45 total tests including bit-level reproducibility assertions, statistical distribution verification between archetypes (`NATURAL_RECOVERER` vs `NON_RESPONSIVE`), counterfactual outcome completeness, expired payment method hard-failure constraints, and seamless integration with the Phase 2 `IngestionService` (`tests/unit/test_simulator.py`).

## [0.2.0] - 2026-08-31
### Added
- **Domain Aggregates**:
  - `PaymentAggregate` and `SubscriptionAggregate` tracking financial state, version counter, and chronologically sorted event timeline (`domain/aggregates.py`).
- **Event Store & Idempotency Abstractions**:
  - `EventStore` interface and `InMemoryEventStore` with chronological event query by `occurred_at` (`ingestion/store.py`).
  - `IdempotencyTracker` interface and `InMemoryIdempotencyTracker` caching execution results and preventing duplicate side-effects (`ingestion/idempotency.py`).
- **State Reconciliation Engine**:
  - `StateReconciler` resolving out-of-order, duplicate, and late event arrivals deterministically (`ingestion/reconciler.py`).
  - Terminal state protection: Preserves `CAPTURED` terminal state when delayed failure webhooks arrive.
  - Strict transition matrix enforcing valid state transitions and raising `InvalidStateTransitionError` on illegal forward mutations.
- **Ingestion Orchestration Service**:
  - `IngestionService` coordinating cryptographic verification, idempotency checking, event appending, and aggregate state reconstruction (`backend/services/ingestion_service.py`).
  - Updated `POST /webhooks/razorpay` to return structured idempotency and state metadata (`backend/api/webhooks.py`).
- **Test Suite**:
  - 39 unit and integration tests including adversarial fintech scenarios: duplicate webhooks, out-of-order `captured` vs `authorized`, late failure absorption, and invalid transition rejection (`tests/unit/test_idempotency.py`, `tests/integration/test_reconciliation.py`).

## [0.1.0] - 2026-08-31
### Added
- **Repository Setup**: Initialized repository structure with `.gitignore`, `pyproject.toml`, and `requirements.txt`.
- **Domain Layer Contracts**:
  - `RevenueState`, `PaymentState`, `SubscriptionState`, `ActionType`, `DecisionType`, and `ActionStatus` enums (`domain/enums.py`).
  - Strict Pydantic v2 event and webhook models (`PaymentEntity`, `SubscriptionEntity`, `WebhookPayload`, `PaymentEvent`) (`domain/events.py`).
  - Strict Pydantic v2 action and decision contracts (`Action`, `ActionParams`, `Decision`, `GuardrailCheckResult`) (`domain/actions.py`).
- **Execution Adapter Boundary**:
  - `RazorpayAdapter` abstract base class defining payment/subscription operations and governed action execution (`execution/base.py`).
  - `MockAdapter` providing in-memory simulation with state tracking without network calls (`execution/mock_adapter.py`).
- **FastAPI Webhook Ingestion & Security**:
  - Secure HMAC SHA-256 webhook signature verification dependency using raw `Request.body()` and constant-time comparison `hmac.compare_digest` (`backend/dependencies/security.py`).
  - Webhook route `POST /webhooks/razorpay` validating signatures and parsing payloads into domain models (`backend/api/webhooks.py`).
  - FastAPI application entrypoint with health check endpoint (`backend/app.py`).
- **Test Suite**:
  - 31 unit and integration tests covering domain validation, MockAdapter state mutation, HMAC signature validation, tamper prevention, missing header rejection, and error handling (`tests/unit/test_domain.py`, `tests/integration/test_webhook_security.py`).
