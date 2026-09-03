# RecoveryOS Technical Boundaries & Known Limitations

In accordance with Track 03 engineering rigor, this document details the architectural boundaries, current constraints, and non-goals of the RecoveryOS platform.

---

## 1. Algorithmic & Modeling Boundaries

### 1.1 Churn Penalty Modeling Assumption
- **Current Implementation**: The evaluation harness applies a default churn friction penalty of ₹2,500 (`250_000` paise) per churned customer as an economic proxy for lost customer lifetime value (LTV).
- **Limitation & Disclosure**: The ₹2,500 penalty is a configurable modeling parameter, not an empirically measured LTV value for a specific merchant cohort. Merchants with higher or lower customer LTVs can configure this threshold in `EvaluationHarness`.

### 1.2 Synthetic Ground-Truth vs Live Empirical Estimation
- **Current Implementation**: The deterministic policy currently evaluates expected incremental value using parameterized static probability priors (`config.estimated_action_priors`) mapped to failure classes.
- **Production Requirement**: In live production, these priors must be replaced by continuous Bayesian online learning, contextual multi-armed bandits (Thompson Sampling), or gradient-boosted uplift models trained on real merchant payment outcomes.
- **Causal Disclosure**: Performance metrics demonstrated in the simulator do not constitute proof of identical uplift in live merchant environments without stratified A/B testing.

### 1.3 Single-Turn Decisions vs Multi-Turn Conversational Negotiation
- **Current Implementation**: RecoveryOS acts as an autonomous execution agent making discrete per-cycle decisions (`NO_ACTION`, `RETRY_LATER`, `PAYMENT_LINK`, `REMINDER`).
- **Limitation**: The agent does not engage in interactive, multi-turn natural language negotiations (e.g. conversational WhatsApp back-and-forth negotiating custom installment plans). Such workflows require human-in-the-loop escalation gates.

### 1.4 Discrete Bucket Timing Selection vs Continuous Delay Optimization
- **Current Implementation**: The policy evaluates candidates across 5 discrete timing buckets (`IMMEDIATE`, `PLUS_2H`, `PLUS_6H`, `PLUS_12H`, `PLUS_24H`) and manages lifecycle state through `ScheduledLifecycleService`.
- **Limitation**: The system does not perform continuous-time survival analysis, continuous mathematical delay optimization, or individual customer payday alignment. Discrete buckets provide transparent and verifiable deterministic scheduling benchmarks, but are not claimed to be a continuous causal timing optimizer.

### 1.5 Operations Console Prototype vs Enterprise SSO/RBAC
- **Current Implementation**: RecoveryOS includes an interactive, single-page Operations Console (`GET /dashboard`) with real-time Control Room, Recovery Queue, Case Replay, Scenario Lab, Merchant Policy Controls, and Exceptions Audit views.
- **Limitation**: Enterprise multi-tenant Role-Based Access Control (RBAC), SAML/SSO authentication, and external ticketing integrations (e.g. Zendesk/Jira) are out of scope for this prototype and are planned for future platform expansion.

### 1.6 Benchmark Population Scale
- **Current Implementation**: The evaluation harness benchmarks a 100-scenario deterministic population across all archetypes and failure physics for high-speed local verification, with support for multi-seed batch runs up to 5,000 scenarios via `scripts/benchmark.py`.
- **Limitation**: Continuous real-time streaming Monte Carlo simulations at massive scale (100,000+ continuous events/sec) are deferred to distributed cloud deployments.

### 1.7 Human Review Escalation Execution
- **Current Implementation**: The Recovery Governor routes high-value or uncertain decisions to human review with `stop_reason = "HUMAN_REVIEW_REQUIRED"`.
- **Limitation**: In this prototype, human review halts autonomous execution and records audit provenance within the Operations Console without dispatching real-time external webhooks to external ticketing software.

---

## 2. Infrastructure & Persistence Boundaries

### 2.1 In-Memory Reference Store vs Distributed Persistent Storage
- **Current Implementation**: For zero-dependency portability and high-speed unit testing, `InMemoryEventStore`, `InMemoryIdempotencyTracker`, and `DecisionLogStore` store data in local process memory.
- **Production Requirement**: Production deployment requires persistent backends:
  - Event Store: Append-only PostgreSQL / CockroachDB with JSONB audit streams.
  - Idempotency Locks: Distributed Redis clusters with Redlock algorithm.
  - Replay Logs: S3 / GCS immutable blob storage for long-term compliance retention.

### 2.2 Synchronous Loop vs Distributed Asynchronous Task Queues
- **Current Implementation**: `AgentRuntime.run_recovery_loop` executes the observe-decide-execute cycle as an in-process asynchronous coroutine.
- **Production Requirement**: High-volume merchant billing requires distributed task orchestrators (e.g., Temporal.io, Celery, or AWS SQS / Step Functions) with durable timers for multi-day dunning delays (e.g. 24-hour retries).

---

## 3. Network & Gateway Assumptions

### 3.1 Webhook Latency and Gateway Race Conditions
- **Mitigation Implemented**: `StateReconciler` and `Stale Action Protection` absorb late arrivals and cancel in-flight executions if a payment is captured out-of-band.
- **Boundary**: If a payment gateway takes several hours to acknowledge a payment status and webhooks are severely delayed (>24h), the system relies on external reconciliation polling jobs to guarantee eventual consistency.

### 3.2 Customer Consent Synchronization
- **Current Implementation**: `ToolFirewall` accepts `CustomerConsentContext` representing known customer opt-out preferences.
- **Boundary**: RecoveryOS assumes customer consent preferences are updated externally (via CRM webhooks or unsubscribe portal links). If an opt-out event is delayed in reaching the system, the firewall cannot retroactively block an already dispatched notification.
