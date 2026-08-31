# RecoveryOS: Autonomous AI Revenue Recovery Agent

RecoveryOS is an enterprise-grade autonomous revenue recovery and dunning intelligence agent developed for the **Razorpay AI Buildathon 2026 (Track 03)**. The platform ingests asynchronous payment and subscription webhooks securely from Razorpay, reconstructs real-time financial states, and executes governed, bounded recovery decisions.

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
                  EVALUATION & POLICY ENVIRONMENT (Phase 3, 4 & 5)
-----------------------------------------------------------------------------------------
  +-----------------------------------------------------------------------------------+
  | simulator/ (Simulator v1)                                                         |
  |                                                                                   |
  |  [SimulatorConfig] (Seed, Distributions)                                          |
  |        |                                                                          |
  |        v                                                                          |
  |  [Simulator.generate_batch()]                                                     |
  |        |                                                                          |
  |        +-----------------------------------+-----------------------------------+  |
  |        |                                   |                                   |  |
  |        v                                   v                                   v  |
  |  [Public Events]                    [Ground Truth]                   [Hidden Outcomes]    |
  |  - PaymentEvent                     - CustomerArchetype              - Y(no_action)       |
  |  - WebhookPayload                   - FailureClass                   - Y(retry_now)       |
  |        |                                                             - Y(retry_later)     |
  |        v (Sanitized Projection)                                      - Y(payment_link)    |
  |  [PublicScenarioView]                                                - Y(reminder)        |
  |        |                                                                   |              |
  |        +-------------------------> [policy/ / evaluation/policies.py]      |              |
  |                                    - DeterministicRecoveryPolicy (v0)      |              |
  |                                    - Baseline Policies (0, 1, 2, 3)        |              |
  |                                           |                                |              |
  |                                           v                                |              |
  |                                    [PolicyDecision a]                      |              |
  |                                           |                                |              |
  |                                           v                                v              |
  |                                 [evaluation/harness.py] <------------------+              |
  |                                 - Lookup Y(a) vs Y(no_action)                             |
  |                                 - MetricCalculator: Incremental & Net Recovery            |
  |                                 - Emits EvaluationMetrics & EvaluationResult              |
  +-----------------------------------------------------------------------------------+
```

---

## 2. Core Modules & Contracts

### 2.1 Public Policy Boundary & Deterministic Policy (`policy/`)
- **`policy/public_view.py`**:
  - `PublicScenarioView`: Sanitized public scenario projection strictly stripping latent customer archetypes and hidden potential outcomes.
- **`policy/base.py`**:
  - `BasePolicy` & `PolicyDecision`: Canonical policy interfaces supporting structured audit reason codes and expected net recovery estimates.
- **`policy/candidates.py`**:
  - `CandidateGenerator`: Deterministic action admissibility engine enforcing domain rules (e.g. blocking retries for expired payment methods, attempt caps).
- **`policy/scoring.py`**:
  - `ExpectedValueScorer`: Transparent expected net economic value proxy calculator evaluating incremental uplift $\Delta Y = Y(a) - Y(\text{no\_action})$ against action costs.
- **`policy/deterministic.py`**:
  - `DeterministicRecoveryPolicy` ("RECOVERYOS_DETERMINISTIC_V0"): The primary baseline policy featuring candidate generation, proxy scoring, and explicit abstention guards.

### 2.2 Synthetic Simulator (`simulator/`)
- **`simulator/config.py`**:
  - `CustomerArchetype`: `HIGHLY_RESPONSIVE`, `NATURAL_RECOVERER`, `CONTACT_FATIGUED`, `NON_RESPONSIVE`.
  - `FailureClass`: `TRANSIENT_GATEWAY`, `INSUFFICIENT_FUNDS`, `EXPIRED_PAYMENT_METHOD`.
  - `SimulatedActionType`: `NO_ACTION`, `RETRY_NOW`, `RETRY_LATER`, `PAYMENT_LINK`, `REMINDER`.
  - `SimulatorConfig` & `ScenarioConfig`: Parameterized configuration with explicit random seed controls.
- **`simulator/archetypes.py`**:
  - Behavioral response probability matrices, contact fatigue penalties, amount elasticity modifiers, and attempt decay rates.
  - Failure physics constraints (e.g. `EXPIRED_PAYMENT_METHOD` imposes a hard 0% success on automated retries).
- **`simulator/outcomes.py`**:
  - `PotentialOutcomeEngine`: Calculates the complete counterfactual state vector $Y(a)$ across all actions:
    $$P(\text{recovery} \mid a) = \text{clamp}(P_{\text{base}}(a) \times M_{\text{failure}}(a) \times F_{\text{amount}} \times F_{\text{attempt}}, 0.0, 1.0)$$
    Tracks delay, recovered revenue, churn risk, fatigue score, and execution cost.
- **`simulator/entities.py` & `simulator/generator.py`**:
  - Emits `SimulatedScenario` containing public `PaymentEvent` / `WebhookPayload` ready for agent consumption while segregating hidden counterfactual outcomes.

### 2.3 Evaluation Harness & Baseline Suite (`evaluation/`)
- **`evaluation/metrics.py`**:
  - `EvaluationMetrics`: Strict Pydantic v2 model capturing Gross Recovery, Natural Recovery, Incremental Recovery, Net Recovery, Intervention Count, Churn, and Fatigue.
  - `ScenarioEvaluationRecord`: Per-scenario record comparing chosen intervention against baseline natural outcome $Y(\text{no\_action})$.
  - `MetricCalculator`: Aggregates records into final benchmark metrics.
- **`evaluation/policies.py`**:
  - `NoActionPolicy` (Baseline 0): Always abstain to establish organic recovery baseline.
  - `AlwaysRetryPolicy` (Baseline 1): Unconditionally retry immediately on failure.
  - `StaticRulePolicy` (Baseline 2): Diagnostic heuristic mapping error codes to targeted interventions.
  - `ProbabilityOnlyPolicy` (Baseline 3): Greedy probability selection maximizing raw $\arg\max_a P(a \mid x)$ without considering cost or churn.
- **`evaluation/harness.py`**:
  - `EvaluationHarness`: Batch orchestrator projecting `PublicScenarioView` and evaluating decisions against hidden counterfactuals.
  - `EvaluationResult`: Encapsulates aggregate metrics and granular per-scenario traces.

### 2.4 Ingestion & Idempotency Layer (`ingestion/`)
- **`ingestion/idempotency.py`**:
  - `IdempotencyTracker` & `InMemoryIdempotencyTracker`: Tracks processed `event_id` keys and caches execution acknowledgments.
- **`ingestion/store.py`**:
  - `EventStore` & `InMemoryEventStore`: Append-only event stream providing timeline sorting by `occurred_at`.
- **`ingestion/reconciler.py`**:
  - `StateReconciler`: Out-of-order resolution, terminal state preservation (`CAPTURED`, `REFUNDED`), and illegal transition protection.

### 2.5 Domain Layer (`domain/`)
- **`domain/aggregates.py`**:
  - `PaymentAggregate` & `SubscriptionAggregate`.
- **`domain/enums.py`** & **`domain/events.py`** & **`domain/actions.py`**:
  - Explicit Pydantic v2 domain contracts.

### 2.6 Execution Layer (`execution/`)
- **`execution/base.py` & `execution/mock_adapter.py`**:
  - `RazorpayAdapter` and in-memory `MockAdapter`.

---

## 3. Running & Verifying

### 3.1 Running Test Suite
```bash
pytest -v
```

### 3.2 Running Synthetic Simulator & Evaluation Harness
```python
from simulator import Simulator, SimulatorConfig
from evaluation import EvaluationHarness, NoActionPolicy, AlwaysRetryPolicy, StaticRulePolicy, ProbabilityOnlyPolicy
from policy import DeterministicRecoveryPolicy

# 1. Generate deterministic scenario batch
sim = Simulator()
scenarios = sim.generate_batch(SimulatorConfig(seed=42, num_scenarios=100))

# 2. Evaluate policies
harness = EvaluationHarness()
policies = [
    NoActionPolicy(),
    AlwaysRetryPolicy(),
    StaticRulePolicy(),
    ProbabilityOnlyPolicy(),
    DeterministicRecoveryPolicy(),
]
results = harness.evaluate_all(policies, scenarios)

for name, result in results.items():
    m = result.metrics
    print(f"[{name}] Gross: ₹{m.gross_recovered_amount_paise / 100:.2f} | Net: ₹{m.net_recovered_amount_paise / 100:.2f} | Incr: ₹{m.incremental_recovered_amount_paise / 100:.2f} | Interventions: {m.total_interventions}")
```
