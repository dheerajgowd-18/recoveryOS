# RecoveryOS: Autonomous AI Revenue Recovery Agent

RecoveryOS is an enterprise-grade autonomous revenue recovery and dunning intelligence agent developed for the **Razorpay AI Buildathon 2026 (Track 03: AI Revenue Recovery)**. The platform ingests asynchronous payment and subscription webhooks securely from Razorpay, reconstructs real-time financial states, and executes governed, bounded recovery decisions.

---

## 1. System Architecture

```
                       +-------------------------------+
                       |   Razorpay Webhook Dispatch   |
                       +---------------+---------------+
                                       |
                                       | POST /webhooks/razorpay
                                       v
                     +-----------------------------------+
                     | backend/dependencies/security.py  |
                     |  - Raw Body Extraction            |
                     |  - HMAC SHA-256 Signature Check   |
                     |  - Constant-time compare_digest   |
                     +-----------------+-----------------+
                                       | (Verified raw bytes)
                                       v
                     +-----------------------------------+
                     |      backend/api/webhooks.py      |
                     |  - Pydantic v2 Parsing & Valid.   |
                     |  - WebhookPayload Extraction      |
                     +-----------------+-----------------+
                                       |
                                       v
                     +-----------------------------------+
                     | backend/services/ingestion_service|
                     |  - Deterministic Event ID Deriv.  |
                     +---+---------------------------+---+
                         |                           |
        (Duplicate?)     v                           v (Fresh Event)
        +----------------------------+   +----------------------------+
        | ingestion/idempotency.py   |   |    ingestion/store.py      |
        |  - Return Cached Response  |   |  - Append PaymentEvent     |
        +----------------------------+   +-------------+--------------+
                                                       |
                                                       v
                                         +----------------------------+
                                         |   ingestion/reconciler.py  |
                                         |  - Sort by occurred_at     |
                                         |  - Terminal State Guard    |
                                         |  - Transition Matrix Check |
                                         +-------------+--------------+
                                                       |
                                                       v
                                         +----------------------------+
                                         |    domain/aggregates.py    |
                                         |  - PaymentAggregate        |
                                         |  - SubscriptionAggregate   |
                                         +----------------------------+

-----------------------------------------------------------------------------------------
                  CLOSED-LOOP AGENT RUNTIME & EXECUTION (Phases 6 - 8)
-----------------------------------------------------------------------------------------
  +-----------------------------------------------------------------------------------+
  | IngestionService (Webhook intake, idempotent event appending, aggregate state)    |
  |        |                                                                          |
  |        v                                                                          |
  |  [RiskDetector.detect_payment_risk()]                                             |
  |        | (Risk: HIGH/CRITICAL)                                                    |
  |        v                                                                          |
  |  [PublicScenarioView Projection]                                                  |
  |        | (Sanitized public features)                                              |
  |        v                                                                          |
  |  [DeterministicRecoveryPolicy.decide()]                                           |
  |        |                                                                          |
  |        +-----------------------------> (NO_ACTION) ----> [Halt & Abstain]         |
  |        |                                                                          |
  |        v (Active Intervention Candidate)                                          |
  |  [Stale Action Revalidation Check]                                                |
  |        | (Re-verifies aggregate is not terminal)                                  |
  |        v                                                                          |
  |  [ToolFirewall]                                                                   |
  |        | (Validates schema, checks customer consent opt-out, acquires lock)       |
  |        v                                                                          |
  |  [SimulatorExecutor.execute()] <----------> [Hidden Scenario Counterfactuals]     |
  |        | (Synthesizes payment.captured / payment.failed)                          |
  |        v                                                                          |
  |  [IngestionService.process_webhook()] (Reconciles aggregate state)                |
  |        |                                                                          |
  |        +-----------------------------> [Loop until Terminal, Abstain, or Limit]  |
  +-----------------------------------------------------------------------------------+
                                       |
                                       v
                     +-----------------------------------+
                     |         audit/replay.py           |
                     |  - DecisionRecord Provenance      |
                     |  - ReplayEngine Reconstruction    |
                     +-----------------------------------+
```

---

## 2. Core Modules & Contracts

### 2.1 Autonomous Agent Runtime (`agent/`)
- **`agent/runtime.py`**:
  - `AgentRuntime`: Closed-loop recovery controller connecting Ingestion, Risk Detection, Policy, Stale Action Protection, Tool Firewall, and Recovery Execution.
  - `AgentRunResult` & `AgentIterationRecord`: Detailed execution audit trail with financial net value accounting, state before/after snapshots, and halt categorization.
- **`agent/risk.py`**:
  - `RiskDetector` & `RiskAssessment`: Deterministic risk analyzer gating non-failure scenarios.

### 2.2 Safety Governor & Tool Firewall (`governor/`)
- **`governor/firewall.py`**:
  - `ToolFirewall`: Action schema validator, channel & global customer consent checker, and execution key idempotency safeguard.
  - `CustomerConsentContext`: Granular communication preferences model.
- **`governor/exceptions.py`**:
  - `FirewallError`, `ActionBlockedError`, `SchemaValidationError`, `ConsentViolationError`, `DuplicateExecutionError`, `PolicyOutageError`.

### 2.3 Audit & Replay Engine (`audit/`)
- **`audit/decision_log.py`**:
  - `DecisionRecord`: Immutable record storing decision ID, candidate scores, risk levels, selected action, aggregate state transitions, and execution outcomes.
  - `DecisionLogStore`: Append-only in-memory storage for querying and audit inspection.
- **`audit/replay.py`**:
  - `ReplayEngine` & `ReplayRecord`: Reconstructs historical agent decision cycles with full provenance by `decision_id`.

### 2.4 Recovery Execution Layer (`execution/`)
- **`execution/executor.py`**:
  - `RecoveryExecutor`: Abstract execution interface with `ExecutionContext` and `ExecutionResult` contracts.
- **`execution/simulator_executor.py`**:
  - `SimulatorExecutor`: Concrete execution adapter querying scenario counterfactuals and synthesizing resulting Razorpay domain events.
- **`execution/base.py` & `execution/mock_adapter.py`**:
  - `RazorpayAdapter` and in-memory `MockAdapter`.

### 2.5 Public Policy Boundary & Deterministic Policy (`policy/`)
- **`policy/public_view.py`**:
  - `PublicScenarioView`: Sanitized public scenario projection strictly stripping latent customer archetypes and hidden potential outcomes.
- **`policy/base.py`**:
  - `BasePolicy` & `PolicyDecision`: Canonical policy interfaces supporting structured audit reason codes and expected net recovery estimates.
- **`policy/candidates.py`**:
  - `CandidateGenerator`: Deterministic action admissibility engine enforcing domain rules (e.g. blocking retries for expired payment methods, attempt caps).
  - `ExpectedValueScorer`: Transparent expected net economic value proxy calculator evaluating incremental uplift $\Delta Y = Y(a) - Y(\text{no\_action})$ against action costs.
- **`policy/deterministic.py`**:
  - `DeterministicRecoveryPolicy` ("RECOVERYOS_DETERMINISTIC_V0"): The primary baseline policy featuring candidate generation, proxy scoring, and explicit abstention guards.

### 2.6 Synthetic Simulator (`simulator/`)
- **`simulator/config.py`**:
  - `CustomerArchetype`: `HIGHLY_RESPONSIVE`, `NATURAL_RECOVERER`, `CONTACT_FATIGUED`, `NON_RESPONSIVE`.
  - `FailureClass`: `TRANSIENT_GATEWAY`, `INSUFFICIENT_FUNDS`, `EXPIRED_PAYMENT_METHOD`.
  - `SimulatedActionType`: `NO_ACTION`, `RETRY_NOW`, `RETRY_LATER`, `PAYMENT_LINK`, `REMINDER`.
  - `SimulatorConfig` & `ScenarioConfig`: Parameterized configuration with explicit random seed controls and micro-transaction ratios.
- **`simulator/archetypes.py`**:
  - Behavioral response probability matrices, contact fatigue penalties, amount elasticity modifiers, and attempt decay rates.
  - Failure physics constraints (e.g. `EXPIRED_PAYMENT_METHOD` imposes a hard 0% success on automated retries).
- **`simulator/outcomes.py`**:
  - `PotentialOutcomeEngine`: Calculates the complete counterfactual state vector $Y(a)$ across all actions.
- **`simulator/entities.py` & `simulator/generator.py`**:
  - Emits `SimulatedScenario` containing public `PaymentEvent` / `WebhookPayload` ready for agent consumption while segregating hidden counterfactual outcomes.

### 2.7 Evaluation Harness & Baseline Suite (`evaluation/`)
- **`evaluation/metrics.py`**:
  - `EvaluationMetrics`: Pydantic v2 model capturing Gross Recovery, Natural Recovery, Incremental Recovery, Net Recovery, Churn Penalty, Adjusted Net Recovery, Incremental Adjusted Net Recovery, Interventions, and Actions Avoided.
  - `ScenarioEvaluationRecord`: Per-scenario record comparing chosen intervention against baseline natural outcome $Y(\text{no\_action})$.
  - `MetricCalculator`: Aggregates records into final benchmark metrics.
- **`evaluation/policies.py`**:
  - `NoActionPolicy` (Baseline 0): Always abstain to establish organic recovery baseline.
  - `AlwaysRetryPolicy` (Baseline 1): Unconditionally retry immediately on failure.
  - `StaticRulePolicy` (Baseline 2): Diagnostic heuristic mapping error codes to targeted interventions.
  - `ProbabilityOnlyPolicy` (Baseline 3): Greedy probability selection maximizing raw $\arg\max_a P(a \mid x)$.
- **`evaluation/harness.py`**:
  - `EvaluationHarness`: Batch orchestrator projecting `PublicScenarioView` and evaluating decisions against hidden counterfactuals with churn penalties.

### 2.8 Ingestion & Idempotency Layer (`ingestion/`)
- **`ingestion/idempotency.py`**:
  - `IdempotencyTracker` & `InMemoryIdempotencyTracker`: Tracks processed `event_id` keys and caches execution acknowledgments.
- **`ingestion/store.py`**:
  - `EventStore` & `InMemoryEventStore`: Append-only event stream providing timeline sorting by `occurred_at`.
- **`ingestion/reconciler.py`**:
  - `StateReconciler`: Out-of-order resolution, terminal state preservation (`CAPTURED`, `REFUNDED`), and illegal transition protection.

### 2.9 Domain Layer (`domain/`)
- **`domain/aggregates.py`**:
  - `PaymentAggregate` & `SubscriptionAggregate`.
- **`domain/enums.py`** & **`domain/events.py`** & **`domain/actions.py`**:
  - Explicit Pydantic v2 domain contracts.

---

## 3. Running & Verifying

### 3.1 Running Test Suite
```bash
python -m pytest -v
```

### 3.2 Running Signature CLI Showcase
```bash
python scripts/demo.py
```
