# RecoveryOS Architecture Specification

This document provides a comprehensive technical overview of the architecture, component interactions, and data contracts powering RecoveryOS.

---

## 1. Architectural Philosophy & Design Principles

1. **State-First Financial Integrity**: No decision is made based on transient memory or unverified payloads. All actions derive from verified, append-only aggregate state timelines.
2. **Strict Public Policy Boundary**: Autonomous policies operate strictly on observable, sanitized public domain features (`PublicScenarioView`). Hidden ground-truth counterfactuals and latent customer archetypes are completely segregated.
3. **Incremental Value Optimization**: RecoveryOS measures success by incremental uplift ($\Delta Y = Y(a) - Y(\text{no\_action})$) minus direct action costs, preventing value destruction on low-value transactions or natural recoverers.
4. **Fail-Closed Safety Governance**: The `ToolFirewall` intercepts all candidate interventions prior to adapter dispatch, blocking unconsented communications, malformed schemas, and duplicate execution keys.
5. **Deterministic Audit Provenance**: Every autonomous decision produces an immutable `DecisionRecord` allowing the `ReplayEngine` to reconstruct the exact evaluation state, candidate scores, and execution outcome.

---

## 2. Component Pipeline & Data Flow

```
[ Razorpay Gateway Webhooks ]
             |
             v
[ backend/dependencies/security.py ]  --> Verifies HMAC-SHA256 signature using raw request bytes
             |
             v
[ backend/services/ingestion_service.py ]
      |-- 1. Checks IdempotencyTracker (returns cached response if duplicate)
      |-- 2. Appends PaymentEvent to append-only EventStore stream
      |-- 3. StateReconciler reconstructs PaymentAggregate / SubscriptionAggregate
             |
             v
[ agent/runtime.py (AgentRuntime Closed Loop) ]
      |-- 1. RiskDetector: Evaluates payment failure risk
      |-- 2. PublicScenarioView: Projects sanitized public features
      |-- 3. DeterministicRecoveryPolicy:
      |         |-- CandidateGenerator: Filters admissible actions under failure physics
      |         |-- ExpectedValueScorer: Ranks actions by expected net incremental value
      |-- 4. Stale Action Revalidation: Verifies payment hasn't been captured out-of-band
      |-- 5. ToolFirewall (governor/firewall.py):
      |         |-- Action Schema Validation
      |         |-- Customer Communication Consent / Opt-Out Check
      |         |-- Execution Key Idempotency Lock
      |-- 6. SimulatorExecutor / RazorpayAdapter: Dispatches action & emits domain events
      |-- 7. Ingests resulting event back into IngestionService (Observe -> Mutate state)
             |
             v
[ audit/replay.py (ReplayEngine) ]  --> Reconstructs bit-level decision provenance
```

---

## 3. Deep-Dive Component Specifications

### 3.1 Webhook Security & Idempotency Layer
- **HMAC SHA-256 Dependency (`backend/dependencies/security.py`)**: Computes HMAC signatures using raw request bytes extracted directly before JSON deserialization to prevent character encoding attacks. Validates signatures using constant-time `hmac.compare_digest`.
- **Idempotency Tracker (`ingestion/idempotency.py`)**: Derives deterministic event identifiers `evt_{account_id}_{entity_id}_{event}_{created_at}` and caches execution receipts, returning identical responses on duplicates without re-triggering reconciliation.
- **Event Store (`ingestion/store.py`)**: Append-only event stream supporting chronological timeline retrieval by `occurred_at`.

### 3.2 State Reconciliation Engine (`ingestion/reconciler.py`)
- **Out-of-Order Resolution**: Sorts all timeline events by `occurred_at` prior to state machine transitions.
- **Terminal State Protection**: Once an aggregate reaches a terminal state (`CAPTURED`, `REFUNDED`), delayed failure webhooks are absorbed into the audit history without mutating the aggregate's terminal status.
- **Transition Matrix**: Enforces legal state progression (`CREATED -> AUTHORIZED -> CAPTURED -> REFUNDED`), rejecting illegal forward mutations.

### 3.3 Synthetic Revenue-Recovery Simulator (`simulator/`)
- **Behavioral Archetypes (`simulator/archetypes.py`)**: Models 4 customer personas (`HIGHLY_RESPONSIVE`, `NATURAL_RECOVERER`, `CONTACT_FATIGUED`, `NON_RESPONSIVE`) with distinct base response probabilities, contact fatigue penalties, amount elasticity, and attempt decay curves.
- **Failure Physics (`simulator/archetypes.py`)**: Enforces real-world physical constraints (e.g. `EXPIRED_PAYMENT_METHOD` has a hard 0% success rate on automated retries).
- **Counterfactual Potential Outcomes $Y(a)$ (`simulator/outcomes.py`)**: Computes the complete latent outcome vector across all candidate actions for ground-truth benchmark comparison.

### 3.4 Strict Observable Context & Structured Intelligence Layer (`intelligence/`)
- **Observable Recovery Context (`intelligence/context.py`)**: Sanitizes event data into `ObservableRecoveryContext`, exposing only observable error codes, reasons, descriptions, amounts, attempt counts, and interaction history. Strictly hides ground-truth failure classes, archetypes, and potential outcomes.
- **Structured Diagnosis Contract (`intelligence/schemas.py`)**: Defines schema-validated diagnosis objects (`StructuredDiagnosis`) with canonical root cause labels (`DiagnosisLabel`), calibrated confidence scores, observable evidence codes, action recommendations, and timing hints.
- **Groq Open-Weights LLM Provider (`intelligence/providers/groq_provider.py`)**: Uses the official `groq` SDK with model `llama-3.3-70b-versatile` and JSON mode (`response_format={"type": "json_object"}`) to perform structured root-cause inference from sanitized observable contexts. Includes live telemetry (`llm_calls`, `llm_successes`, `llm_fallbacks`, `llm_latency_ms`) and fail-closed fallback to the deterministic provider on timeout, schema errors, or missing keys.
- **Deterministic Offline Provider (`intelligence/providers/deterministic.py`)**: Infers structured root-cause diagnoses purely offline from observable error signatures with 0 external API dependencies.

### 3.5 Candidate Generation & Negative Uplift Scorer (`policy/`)
- **Candidate Generator (`policy/candidates.py`)**: Filters candidate interventions based on structured diagnosis diagnostics and attempt limits (e.g. blocking retries on expired cards, capping attempts on insufficient funds).
- **Expected-Value Proxy Scorer (`policy/scoring.py`)**: Calculates expected incremental value with full negative uplift support:
  $$\text{Expected Net Value} = (\text{Amount} \times \Delta P) - \text{Action Cost}$$
  $$\Delta P = P_{\text{prior}}(a) - P_{\text{prior}}(\text{no\_action}) \quad (\Delta P \text{ may be negative})$$
- **Deterministic Policy (`policy/deterministic.py`)**: Ranks candidates, applies diagnosis confidence gates and net value thresholds, and explicitly abstains (`NO_ACTION`) when confidence is low or expected net return is negative.

### 3.6 Closed-Loop Agent Runtime (`agent/runtime.py`)
- **State Guarded Loop**: Bounded by `max_iterations = 5`, executing the observe -> diagnose -> decide -> execute sequence.
- **Stale Action Protection**: Re-inspects aggregate state immediately prior to executor dispatch, canceling in-flight retries if the customer paid out-of-band.

### 3.7 Recovery Governor v1 & Safety Tool Firewall (`governor/`)
- **Recovery Governor (`governor/recovery_governor.py`, `governor/checks.py`)**: Authoritative governance engine evaluating proposals against merchant operational limits. Runs deterministic checks in fixed priority order:
  1. *State Validity & Terminal State*: Denies actions if payment is already captured/refunded (`REVENUE_ALREADY_RECOVERED`, `STATE_INVALID`).
  2. *Recovery Window*: Denies actions outside the recovery window (`RECOVERY_WINDOW_EXPIRED`).
  3. *Customer Consent*: Denies customer-facing actions for opted-out users (`CUSTOMER_OPTED_OUT`).
  4. *Action Whitelist*: Denies unapproved dunning channels (`ACTION_NOT_ALLOWED_BY_POLICY`).
  5. *Retry Limits & Contact Caps*: Enforces attempt caps and 24h/7d communication limits (`RETRY_LIMIT_REACHED`, `CONTACT_LIMIT_REACHED`).
  6. *Cooldown Enforcement*: Defers active dunning within cooldown intervals (`COOLDOWN_ACTIVE`).
  7. *Amount Thresholds & Human Review*: Escalates high-value transactions or diagnosis uncertainty to human operators (`HUMAN_REVIEW_REQUIRED`).
  8. *Economic Viability*: Confirms abstention on negative uplift or low expected return (`NEGATIVE_INCREMENTAL_UPLIFT`, `EXPECTED_VALUE_BELOW_THRESHOLD`).
- **Merchant Policy Contract (`governor/policy.py`)**: Formalizes configurable, versioned merchant rules (`MerchantPolicy`) and automation modes (`AUTONOMOUS`, `ASSISTED`, `MANUAL`).
- **Human Review Escalator (`governor/human_review.py`)**: Routes ambiguous, high-value, or low-confidence decisions to human review with explicit stop reasons and reason codes.
- **Tool Firewall (`governor/firewall.py`)**: Acts as an independent second line of defense immediately prior to adapter dispatch, enforcing strict schema validation and execution key idempotency locks.

### 3.8 Action × Timing Decision Model & Scheduled-Action Lifecycle (`planner/`, `scheduler/`)
- **Action Mechanisms & Discrete Timing Windows (`planner/timing.py`)**: Formalizes explicit action mechanisms (`NO_ACTION`, `RETRY`, `PAYMENT_LINK`, `REMINDER`, `HUMAN_REVIEW`) across discrete timing buckets (`IMMEDIATE` [0s], `PLUS_2H` [7,200s], `PLUS_6H` [21,600s], `PLUS_12H` [43,200s], `PLUS_24H` [86,400s]).
- **Candidate Generator (`TimingCandidateGenerator`)**: Generates admissible (Mechanism × Timing Window) candidate pairs bounded by failure physics (e.g. no retries on expired cards, immediate retry only on attempt 1 when allowed, delayed retries for transient gateway timeouts).
- **Deterministic Timing Estimator (`DeterministicTimingValueEstimator`)**: Transparent mathematical scoring of expected net value without simulator oracle leakage:
  $$\text{ExpNetValue} = (\text{Amount} \times (P_{\text{mech}}(\text{timing}) \times \text{Confidence} - P_{\text{natural}})) - \text{Cost}_{\text{mech}}$$
- **Scheduled Action Store (`scheduler/store.py`)**: Thread-safe in-memory store indexing active scheduled actions by ID, payment ID, and execution idempotency key.
- **Scheduled Lifecycle Service (`scheduler/service.py`)**: Manages the complete lifecycle:
  1. *Schedule*: Persists delayed actions with status `PENDING`, `expected_state_version`, and `expires_at_epoch`.
  2. *Revalidation*: Pre-execution state verification checking current aggregate version, terminal status, and window expiry (`STATE_VERSION_MISMATCH`, `REVENUE_ALREADY_RECOVERED`, `TIMING_EXPIRED_BEFORE_EXECUTION`).
  3. *Invalidation*: Cancels stale actions if payment is captured or refunded out-of-band.
  4. *Execution*: Passes valid due actions through `ToolFirewall` gating to execution.

### 3.9 Audit & Decision Replay Engine (`audit/`)
- **Immutable Decision Log (`audit/decision_log.py`)**: Stores complete decision records including observable context snapshots, structured diagnosis, Governor verdict, timing window, delay seconds, scheduled action ID, candidate score arrays, chosen action, confidence, and execution outcomes.
- **Replay Engine (`audit/replay.py`)**: Reconstructs historical decision states, structured diagnoses, Governor verdicts, timing windows, and score breakdowns by `decision_id` for compliance audits and post-mortem analysis.

### 3.10 Operations Console & Dashboard Architecture (`dashboard/`)
- **Web Interface Architecture (`dashboard/routes.py`, `dashboard/templates/dashboard.html`)**: FastAPI-served single-page console built with Jinja2 templates, Tailwind CSS, and Alpine.js. Operates with 0 Node.js build dependencies.
- **Aggregated Data Service (`dashboard/service.py`)**: `DashboardService` singleton querying across in-memory decision logs, scheduled action registries, merchant governance policies, and on-disk benchmark evaluation reports (`reports/benchmark_detail.json`).
- **Strict Observable Boundary Protection**: Ensures no unobservable simulator ground truth ($Y(a)$ potential outcomes, customer archetypes) is ever exposed through dashboard APIs.
- **Five Core Operational Views**:
  1. *Merchant Control Room (`GET /dashboard/api/control-room`)*: Live surveillance of Revenue at Risk, Gross Recovered, Incremental Net Recovery, Interventions Avoided, and real-time event telemetry.
  2. *Recovery Queue (`GET /dashboard/api/recovery-queue`)*: Ledger of failed transactions ranked by recovery priority and expected incremental value.
  3. *Case Decision Replay (`GET /dashboard/api/cases/{case_id}/replay`)*: Step-by-step chronological audit provenance reconstructing "Why We Acted" vs "Why We Did Not Act".
  4. *Evaluation Lab (`GET /dashboard/api/evaluation`)*: Statistical baseline comparison table, theoretical Oracle hindsight ceiling, regret distribution, and multi-parameter sensitivity grid.
  5. *Exceptions & Audit (`GET /dashboard/api/exceptions`)*: Real-time exceptions log monitoring stale action invalidations, consent opt-outs, and human review escalations.

### 3.11 Razorpay Gateway Integration & Test Adapter (`ingestion/`, `execution/`)
- **HMAC SHA-256 Webhook Verification (`ingestion/razorpay_webhook.py`, `backend/dependencies/security.py`)**: Validates the raw request body bytes against the `X-Razorpay-Signature` header using `hmac.compare_digest` in constant time. Malformed or unverified payloads are dropped with HTTP 401 Unauthorized before reaching application state.
- **Razorpay Test-Mode Execution Adapter (`execution/razorpay_adapter.py`)**:
  - Implements the `RecoveryExecutor` contract to call real Razorpay Test APIs via asynchronous HTTP (`httpx`).
  - Methods include `fetch_payment_status(payment_id)` and `create_payment_link(payment_id, amount, customer_details)`.
  - **Fail-Closed Credential Security**: Reads `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` from environment variables. If unconfigured or detected as placeholder text, the adapter safely fails closed, logging a sanitized warning and emitting an abstention/failure record without exposing secrets or crashing.
