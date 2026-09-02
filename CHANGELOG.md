# Changelog

All notable changes to the RecoveryOS platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-09-02

### Added
- **Final Submission Freeze & Configuration Lock (`config/freeze.json`)**:
  - Locked benchmark evaluation seeds: Development seeds `[42, 43, 44]`, Holdout seeds `[45, 46]`.
  - Locked policy specification version: `v2.0.0`.
  - Locked diagnosis model version: `deterministic-v1`.
  - Locked scenario generator schema version: `2.0.0`.
- **Exhaustive Adversarial Edge-Case Suite (`tests/adversarial/test_final_edge_cases.py`)**:
  - Added 7 end-to-end automated adversarial tests covering:
    1. Late authorization invalidating scheduled retries before dispatch.
    2. Customer communication opt-outs blocked independently at both Recovery Governor and Tool Firewall.
    3. Policy engine and LLM provider outages failing closed safely to conservative `NO_ACTION`.
    4. Duplicate webhook delivery deduplication with strict HMAC and idempotency preservation.
    5. Out-of-order event reconciliation rejecting invalid state transitions.
    6. High-value transactions exceeding merchant risk limits escalating to human review.
    7. Negative expected uplift triggering deliberate economic abstention to eliminate destructive fees.
  - Test suite expanded to **183 passing automated unit, integration, benchmark, and adversarial tests** with 0 warnings.
- **5-Minute Pitch & Demo Choreography (`DEMO.md`, `PITCH.md`)**:
  - Timed 5-minute panel presentation breakdown covering problem hook, signature cases, Evaluation Lab multi-seed proof, and architectural governance.
  - Sub-5-second execution guarantee for `make demo` and `make test`.

## [1.6.0] - 2026-09-02

### Added
- **Razorpay Webhook Signature Verification (`ingestion/razorpay_webhook.py`)**:
  - Strict HMAC-SHA256 signature verification using the `X-Razorpay-Signature` header and raw request body.
  - Constant-time `hmac.compare_digest` verification preventing timing side-channel attacks.
  - Normalization of incoming raw JSON payloads into canonical `WebhookPayload` domain models.
- **Razorpay Test-Mode Execution Adapter (`execution/razorpay_adapter.py`)**:
  - Implemented `RazorpayAdapter` inheriting from `RecoveryExecutor` contract to execute test-mode interventions against `https://api.razorpay.com/v1/`.
  - Added methods `fetch_payment_status(payment_id)` and `create_payment_link(payment_id, amount, customer_details)`.
  - **Fail-Closed Security**: Gracefully checks `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`. Fails closed safely if credentials are missing or placeholders, preventing unhandled runtime exceptions and protecting API keys from exposure.
- **Live Webhook Endpoint Verification (`backend/app.py`, `backend/api/webhooks.py`)**:
  - Verified `POST /webhooks/razorpay` endpoint accepting HMAC-verified webhooks and returning HTTP 200 with structured ingestion receipt or HTTP 401 on tampered signatures.
- **Configuration & Environment (`.env.example`)**:
  - Added `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` configuration template.
- **Integration Test Suite (`tests/integration/test_razorpay_integration.py`)**:
  - Added 7 comprehensive integration tests covering valid webhook signature verification, invalid signature rejection (HTTP 401), adapter fail-closed behavior on missing/placeholder credentials, and mocked Razorpay test API executions (176 total passing tests).

## [1.5.0] - 2026-09-02

### Added
- **RecoveryOS Operations Console & Dashboard (`dashboard/`, `GET /dashboard`)**:
  - FastAPI-served single-page browser console built with Jinja2 templates, Tailwind CSS, and Alpine.js (zero Node.js/npm/Vite build steps).
  - Modern fintech operational dark theme with tabular figures (`font-mono tabular-nums`), dense informational tables, and semantic badge indicators.
  - 5 core operational views:
    1. **Merchant Control Room**: Top KPI strip (Revenue at Risk, Gross Recovered, Incremental Recovered, Net Adjusted Recovery, Active Opportunities, Actions Executed/Avoided, Human Reviews, Policy Blocks) and live event activity feed.
    2. **Recovery Queue**: Ledger of active failure cohorts prioritized by ticket value, risk tier, root cause diagnosis, and expected incremental uplift.
    3. **Case Decision Replay**: Chronological decision provenance reconstructing exact 7-step reasoning pipeline with "Why We Acted" vs "Why We Did Not Act" analytical summaries.
    4. **Evaluation Lab**: Batch statistical proof displaying multi-seed baseline policy comparisons, Oracle hindsight ceiling, regret distribution, and economic sensitivity matrix.
    5. **Exceptions & Audit**: Real-time surveillance of stale scheduled actions, customer consent opt-outs, and human review escalations.
- **Aggregated Operations Service (`dashboard/service.py`)**:
  - `DashboardService` singleton aggregating across in-memory decision logs, scheduled action registries, merchant policies, and on-disk benchmark reports.
  - Automatically bootstraps 5 signature fintech cases for immediate zero-config exploration.
- **Operations Console JSON APIs (`dashboard/routes.py`)**:
  - `GET /dashboard/api/control-room`
  - `GET /dashboard/api/recovery-queue`
  - `GET /dashboard/api/cases/{case_id}/replay`
  - `GET /dashboard/api/evaluation`
  - `GET /dashboard/api/policies`
  - `GET /dashboard/api/exceptions`
- **Strict Privacy & Observable Context Boundary Enforcement**:
  - Validated that no unobservable counterfactual simulation ground truth ($Y(a)$ potential outcomes, customer archetypes) is ever exposed through dashboard APIs.
- **Unit Test Suite Expansion (`tests/unit/test_dashboard.py`)**:
  - Added 8 new unit tests validating HTML route rendering, all JSON telemetry APIs, 404 handling, and privacy boundary isolation (166 total passing tests).

## [1.4.1] - 2026-09-02

### Fixed
- **Dependency Hygiene (`requirements.txt`, `pyproject.toml`)**:
  - Explicitly declared `numpy>=1.24.0` in both `requirements.txt` and `pyproject.toml` dependencies.
- **Oracle & Regret Metric Semantic Alignment (`evaluation/oracle.py`, `evaluation/regret.py`, `evaluation/benchmark_runner.py`)**:
  - Re-anchored Oracle maximization and regret metrics strictly to **Incremental Adjusted Net Recovery** relative to the organic baseline $Y(\text{NO\_ACTION})$.
  - Guaranteed non-negative Oracle incremental potential ($\ge 0$).
  - Proved and enforced the exact population reconciliation identity: $\text{Incremental Gap} = \text{Total Regret} = \sum_{i=1}^N \text{Regret}_i$.
  - Fixed multi-seed per-scenario regret pooling to preserve distinct seed namespaces.
- **Canonical Metric Naming & Reporting (`evaluation/reports.py`, `scripts/benchmark.py`, `EVALUATION.md`)**:
  - Standardized terminology across markdown reports and CLI summaries: `Oracle Incremental Adjusted Net`, `RecoveryOS Incremental Adjusted Net`, `Incremental Gap`, `Total Regret`, `Mean Regret`, `Median Regret`, `P95 Regret`, `Zero-Regret Rate`.
- **Git Hygiene (`.gitignore`)**:
  - Excluded `reports/` and `reports/*` directory in `.gitignore` so generated benchmark artifacts remain local.
- **Unit Test Suite Expansion (`tests/unit/test_benchmark_expansion.py`)**:
  - Added packaging manifest dependency checks, gitignore exclusion tests, and exact mathematical reconciliation assertions (158 total passing tests).

## [1.4.0] - 2026-09-02

### Added
- **Expanded Evaluation Lab & Multi-Seed Benchmark Runner (`evaluation/benchmark_runner.py`, `scripts/benchmark.py`)**:
  - `BenchmarkConfig` model supporting configurable scenario counts, seed lists, holdout seeds, churn penalty grids, and output directories.
  - Multi-seed statistical aggregation computing mean, sample standard deviation, median, min, max, and 95% Confidence Intervals across seed cohorts.
  - Dataset split segregation separating development seeds (`42, 43, 44` - 3,000 scenarios) from strictly untuned holdout seeds (`45, 46` - 2,000 scenarios) and combined cohorts.
- **Theoretical Counterfactual Oracle Benchmark (`evaluation/oracle.py`)**:
  - `OraclePolicy` implementing perfect hindsight of counterfactual outcomes $Y(a)$ to establish the diagnostic ceiling.
  - `OracleComparisonResult` computing theoretical maximum incremental adjusted net recovery and RecoveryOS efficiency percentage (56.3% of Oracle potential on 5,000-scenario cohort).
- **Evaluator-Side Decision Regret Framework (`evaluation/regret.py`)**:
  - `RegretCalculator` computing non-negative scenario-level regret ($\text{Regret} = \text{OracleIncrNet} - \text{ChosenIncrNet} \ge 0$).
  - `RegretSummary` tracking total regret, mean regret, median regret, 95th percentile tail risk, maximum single-scenario regret, and zero-regret rate.
- **Economic Sensitivity Analysis Engine (`evaluation/sensitivity.py`)**:
  - `SensitivityAnalyzer` executing full grid sweeps across churn penalties (₹1,000, ₹2,500, ₹5,000) and action cost multipliers ($0.5\times, 1.0\times, 2.0\times$).
  - 100% Win Rate (9/9 parameter cells) proving economic robustness of RecoveryOS over baseline heuristics.
- **Standardized Benchmark Report Generator (`evaluation/reports.py`)**:
  - Automatically exports `reports/benchmark_summary.md`, `reports/benchmark_detail.json`, `reports/sensitivity_matrix.md`, and `reports/failures.json`.
- **CLI Benchmark Tool (`scripts/benchmark.py`)**:
  - Configurable CLI utility supporting custom scenario counts and seed lists while preserving fast interactive `scripts/demo.py`.

## [1.3.0] - 2026-09-01

### Added
- **Action × Timing Decision Model (`planner/timing.py`, `planner/`)**:
  - `TimingWindow` enum formalizing 5 discrete timing buckets (`IMMEDIATE`, `PLUS_2H`, `PLUS_6H`, `PLUS_12H`, `PLUS_24H`) with exact `delay_seconds`.
  - `ActionMechanism` enum formalizing distinct recovery mechanisms (`NO_ACTION`, `RETRY`, `PAYMENT_LINK`, `REMINDER`, `HUMAN_REVIEW`).
  - `ActionTimingCandidate` model evaluating mechanism-window combinations.
  - `TimingCandidateGenerator` filtering admissible Action × Timing pairs based on physical failure diagnostics, attempt caps, and policy flags.
  - `DeterministicTimingValueEstimator` estimating expected probability, uplift, and net value for candidates deterministically without simulator oracle leakage.
- **Lightweight Scheduled-Action Lifecycle Package (`scheduler/`)**:
  - `ScheduledAction` model with status transitions (`PENDING`, `DUE`, `EXECUTED`, `CANCELLED`, `INVALIDATED`, `EXPIRED`), `expected_state_version`, `expires_at_epoch`, and execution idempotency keys.
  - `InMemoryScheduledStore` providing thread-safe indexed lookups and idempotency deduplication.
  - `ScheduledLifecycleService` managing scheduling, pre-execution revalidation, stale action invalidation, and expiration.
- **Runtime & Governor Timing Integration (`agent/runtime.py`, `governor/`)**:
  - Bound `ScheduledLifecycleService` into `AgentRuntime`.
  - When Governor allows a delayed action, `AgentRuntime` schedules the action and stops the loop with `stop_reason = "ACTION_SCHEDULED"`.
  - Implemented `execute_due_scheduled_action` verifying aggregate state version, checking stale state, gating through `ToolFirewall`, executing via adapter, and updating store status.
  - Extended `RecoveryGovernor` to enforce recovery window boundaries (`TIMING_OUTSIDE_RECOVERY_WINDOW`), merchant delayed permissions, and cooldown deferrals.
- **Comprehensive Timing & Scheduler Test Suite (`tests/unit/test_timing_scheduler.py`)**:
  - Added 15 comprehensive unit tests covering candidate generation, deterministic value estimation, negative uplift, Governor timing validation, scheduler state versioning, pre-execution invalidation, window expiry, and idempotency deduplication (145 total passing tests).
- **Evaluation & Audit Counters**:
  - Added `actions_scheduled_count`, `actions_executed_immediately_count`, `scheduled_actions_invalidated_count`, and `scheduled_actions_expired_count` to evaluation metrics and demo tables.

## [1.2.0] - 2026-09-01

### Added
- **Recovery Governor v1 & Governance Package (`governor/`)**:
  - `GovernorDecision` contract with canonical decision results (`ALLOW`, `DENY`, `DEFER`, `ESCALATE`, `ABSTAIN`), machine-readable reason codes, and human review triggers.
  - `MerchantPolicy` contract formalizing versioned operational policies, automation modes (`AUTONOMOUS`, `ASSISTED`, `MANUAL`), retry caps, 24h contact limits, amount thresholds, and cooldown windows.
  - `GovernanceChecker` executing ordered deterministic governance checks (state validity, recovery window, consent, whitelist, limits, cooldowns, amount caps, human review, confidence thresholds, and negative uplift).
  - `HumanReviewEvaluator` routing high-value transactions, borderline confidence cases, and manual mode decisions to human review with `stop_reason = 'HUMAN_REVIEW_REQUIRED'`.
  - `RecoveryGovernor` authority orchestrator evaluating proposals prior to execution.
- **Evaluation & Audit Governance Metrics**:
  - Extended `EvaluationMetrics` and `EvaluationHarness` to track `governor_allow_count`, `governor_deny_count`, `governor_abstain_count`, `governor_defer_count`, `human_review_count`, `policy_block_count`, `consent_block_count`, `retry_limit_block_count`, and `contact_limit_block_count`.
  - Updated `DecisionRecord` and `ReplayRecord` with `governor_decision`, `governor_reason_codes`, `governor_policy_version`, and `human_review_reason`.
- **Comprehensive Governor Test Suite (`tests/unit/test_governor.py`)**:
  - Added 13 unit tests validating allowance, consent denial, retry/contact limits, cooldown deferral, human review escalation, fail-closed policy outages, and firewall independence (130 total passing tests).

### Changed
- `agent/runtime.py`: Integrated `RecoveryGovernor` into the recovery cycle between policy proposal and tool firewall execution.
- `scripts/demo.py`: Showcases explicit Governor verdicts across signature demo cases.

## [1.1.0] - 2026-09-01

### Added
- **Structured Intelligence Layer & Diagnosis Provider (`intelligence/`)**:
  - `StructuredDiagnosis` contract with canonical root-cause taxonomy (`DiagnosisLabel`), calibrated confidence, observable evidence codes, recommended candidate actions, and timing hints.
  - `ObservableRecoveryContext` and `ObservableContextBuilder` providing a strict public boundary free of latent simulator truth (no `failure_class`, `archetype`, or `hidden_outcomes` leakage).
  - `DeterministicDiagnosisProvider` providing pure offline rule-based diagnosis inference with zero external API dependencies.
  - `LLMDiagnosisProvider` boundary supporting structured LLM outputs with Pydantic validation and automatic fallback (`diagnosis_source = 'deterministic_fallback'`).
- **Negative Incremental Uplift Semantics**:
  - Refactored `ExpectedValueScorer` to compute $\Delta P = P(a) - P(\text{no\_action})$ without artificial zero-clipping, enabling explicit negative uplift calculation and negative expected net value tracking.
  - Added low-confidence diagnosis abstention guards (`confidence < threshold`) and negative uplift abstention flags in `DeterministicRecoveryPolicy`.
- **Evaluator-Side Diagnosis Verification**:
  - Added `diagnosis_accuracy`, `diagnosis_source_counts`, `deterministic_fallback_count`, and `invalid_llm_output_count` to `EvaluationMetrics` and `EvaluationHarness`.
- **Comprehensive Intelligence Test Suite (`tests/unit/test_intelligence.py`)**:
  - Added 12 unit tests validating context segregation, deterministic inference, LLM validation and fallback, negative uplift abstention, and baseline compatibility under observable context (117 total passing tests).

### Changed
- `policy/public_view.py`: Refactored `PublicScenarioView` to inherit from `ObservableRecoveryContext` without exposing simulator ground-truth failure classes.
- `agent/runtime.py`: Integrated `ObservableContextBuilder` and `DiagnosisProvider` into the closed-loop recovery sequence.
- `audit/decision_log.py` & `audit/replay.py`: Upgraded audit models to capture structured diagnosis, confidence, provider source, and candidate score breakdowns.

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
