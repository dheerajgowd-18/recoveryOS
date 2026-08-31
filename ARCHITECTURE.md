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

### 3.4 Public Policy Boundary & Deterministic Policy (`policy/`)
- **Public Scenario Projection (`policy/public_view.py`)**: Sanitizes scenario data into `PublicScenarioView`, exposing only observable error codes, reasons, amounts, and attempt counts.
- **Candidate Generator (`policy/candidates.py`)**: Filters candidate interventions based on physical failure diagnostics (e.g. disallowing retries on expired cards, enforcing attempt limits on insufficient funds).
- **Expected-Value Proxy Scorer (`policy/scoring.py`)**: Calculates expected incremental value:
  $$\text{Expected Net Value} = (\text{Amount} \times \Delta P) - \text{Action Cost}$$
  $$\Delta P = \max(0.0, P_{\text{prior}}(a) - P_{\text{prior}}(\text{no\_action}))$$
- **Deterministic Policy (`policy/deterministic.py`)**: Ranks candidates, applies net value thresholds, and explicitly abstains (`NO_ACTION`) when expected net return is negative.

### 3.5 Closed-Loop Agent Runtime (`agent/runtime.py`)
- **State Guarded Loop**: Bounded by `max_iterations = 5`, terminating on recovery (`REVENUE_RECOVERED`), abstention (`POLICY_ABSTAINED`), terminal state (`TERMINAL_STATE_REACHED`), or fault (`POLICY_OUTAGE`, `EXECUTION_FAILURE`).
- **Stale Action Protection**: Re-inspects the aggregate state immediately prior to executor dispatch, canceling in-flight retries if the customer paid out-of-band.

### 3.6 Tool Firewall & Safety Governor (`governor/`)
- **Schema Validation**: Rejects unrecognized action names or illegal parameter structures.
- **Consent Enforcement**: Rejects customer-facing communications (`PAYMENT_LINK`, `REMINDER`) when customer opt-out preferences are recorded.
- **Idempotency Locking**: Blocks duplicate execution keys `exec_{payment_id}_{iteration}_{action}_{epoch}`.

### 3.7 Audit & Decision Replay Engine (`audit/`)
- **Immutable Decision Log (`audit/decision_log.py`)**: Stores complete decision records including input snapshots, candidate score arrays, chosen action, confidence, and execution outcomes.
- **Replay Engine (`audit/replay.py`)**: Reconstructs historical decision states and score breakdowns by `decision_id` for compliance audits and post-mortem analysis.
