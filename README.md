# RecoveryOS

### Policy-Governed AI for Incremental Revenue Recovery

[![CI Suite](https://img.shields.io/badge/CI%20Suite-339%20passed-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue.svg)]()
[![Razorpay AI Buildathon 2026](https://img.shields.io/badge/Track%2003-AI%20Revenue%20Recovery-blueviolet.svg)]()
[![LLM Layer](https://img.shields.io/badge/LLM-Groq%20%7C%20Deterministic%20Fallback-indigo.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

> **Razorpay AI Buildathon 2026 · Track 03 — AI Revenue Recovery**  
> **Positioning**: *Policy-governed AI for incremental revenue recovery under uncertainty.*  
> **Central Thesis**: Most recovery systems optimize for recovered volume. RecoveryOS optimizes for the incremental revenue that an intervention actually adds beyond what would have resolved naturally.  
> **Core Operating Invariant**:
> $$\text{AI proposes} \longrightarrow \text{Economic Policy decides} \longrightarrow \text{Governor authorizes} \longrightarrow \text{Executor acts} \longrightarrow \text{State verifies}$$

---

## 1. Executive Overview

RecoveryOS is a closed-loop revenue recovery system designed for subscription merchants, SaaS platforms, and digital commerce. When a payment fails, RecoveryOS diagnoses the underlying root cause, evaluates candidate action and timing windows against expected net recovery, enforces deterministic financial guardrails through a non-bypassable Governor, dispatches bounded recovery actions, and verifies final state via Razorpay webhooks.

```
                  ┌──────────────────────────────────────────────────────────┐
                  │                 THE CENTRAL OPERATIONAL RULE             │
                  │                                                          │
                  │   "Sometimes the best recovery action is no action."     │
                  │                                                          │
                  │   AI proposes candidate actions.                         │
                  │   Deterministic economic policy decides expected yield.  │
                  │   The Recovery Governor authorizes against merchant caps.│
                  │   The Executor dispatches bounded API workflows.         │
                  │   Payment state reconciliation verifies actual outcomes. │
                  └──────────────────────────────────────────────────────────┘
```

---

## 2. The Financial Problem

A failed payment does not automatically equal lost revenue. In fintech billing environments, naive retry bots treat every failure as an emergency—spamming customer payment links, burning gateway fees, triggering customer support escalations, and claiming credit for payments that would have resolved organically.

```
TRADITIONAL RECOVERY (Naive Volume Chaser):
  FAILED PAYMENT ──────► BLIND RETRY ──────► SPAM CUSTOMER ──────► COUNT GROSS RECOVERY
  (High gateway surcharge fees • Severe customer contact fatigue • Unnecessary churn)

RECOVERYOS (Economic & Policy Governed):
  FAILED PAYMENT ──────► DIAGNOSE ROOT CAUSE ──────► ESTIMATE INCREMENTAL VALUE
                                                             │
  OUTCOME VERIFIED ◄────── ACT OR ABSTAIN ◄────── GOVERNOR AUTHORIZATION
```

Depending on the failure archetype, customers may:
- **Recover naturally** without any intervention (e.g., temporary bank maintenance during salary hours).
- **Require delayed retry** to permit upstream banking switches to recover.
- **Require a payment link** to collect an alternate payment instrument (e.g., expired mandate).
- **Require human escalation** due to high ticket value or fraud uncertainty.
- **Be better left untouched** when transaction value is less than action costs and friction.

---

## 3. Why RecoveryOS Is Different

| Dimension | Conventional Recovery Tools | RecoveryOS |
| :--- | :--- | :--- |
| **Optimization Target** | Gross recovered volume ($\sum Y(a)$) | **Incremental adjusted net revenue** ($\Delta Y_{\text{adj}}$) |
| **Intervention Policy** | Fixed cron schedules (e.g., Retry at Day 1, 3, 5) | **Action $\times$ Timing optimization** evaluated per case |
| **Abstention** | Impossible; always triggers communication | **First-class decision**; deliberately abstains when net value $< 0$ |
| **Financial Authority** | Unbounded scripts or unrestricted LLM calls | **Deterministic Governor & Tool Firewall** authorize every action |
| **State Awareness** | Blindly dispatches scheduled jobs | **State-versioned scheduling**; invalidates stale retries if customer pays |
| **Customer Protection** | Relies on manual suppression lists | **Hard consent opt-out enforcement** and contact caps ($24\text{h} / 7\text{d}$) |
| **Auditability** | Opaque webhook logs | **7-layer Decision Anatomy Matrix** with contrastive explanations |
| **Evaluation Honesty** | Cherry-picked success metrics | **Multi-seed benchmarks** vs baselines, Oracle ceiling, and regret analysis |

---

## 4. System Architecture

RecoveryOS enforces separation of concerns across five sovereign planes. The LLM provides reasoning assistance; it never possesses financial authority or direct execution capabilities.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                 INCOMING RAZORPAY WEBHOOKS                              │
│                                (X-Razorpay-Signature HMAC SHA-256)                      │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. OBSERVE & RECONCILE PLANE (backend/, ingestion/)                                     │
│    • Ingestion Service & Idempotency Store                                              │
│    • Event-Sourced Payment Aggregate Reconstruction                                     │
│    • State Reconciliation (CREATED ➔ FAILED ➔ CAPTURED ➔ CLOSED)                        │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ 2. INTELLIGENCE PLANE (agent/, intelligence/, rag/)                                     │
│    • Observable Context Builder (strictly isolates simulator ground truth)             │
│    • Bounded Recovery Memory & Merchant Playbook Retrieval                              │
│    • Diagnosis Provider: Groq (openai/gpt-oss-120b) with Deterministic Rule Fallback    │
│    • Strategy Synthesis: Generates candidate mechanisms                                │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ 3. ECONOMIC DECISION PLANE (policy/, planner/)                                          │
│    • Timing Candidate Generator (IMMEDIATE, PLUS_2H, PLUS_6H, PLUS_12H, PLUS_24H)       │
│    • Deterministic Net Value Estimator: Computes expected incremental yield             │
│    • Deliberate Abstention: Selects NO_ACTION if all candidates produce negative yield  │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ 4. SAFETY & CONTROL PLANE (governor/)                                                   │
│    • Recovery Governor: Enforces 8 merchant policy invariants                           │
│    • Customer Consent Gate: Verifies opt-out status (DENY on opt-out)                   │
│    • Cooldown & Frequency Caps: Enforces max retries and 24h contact limits             │
│    • Tool Firewall: Strict whitelist gateway and payload schema validator               │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                      ┌──────────────────────┴──────────────────────┐
                      ▼                                             ▼
          [ IMMEDIATE EXECUTION ]                       [ SCHEDULED LIFECYCLE ]
                      │                                             │
                      │                                             ▼
                      │                                  Revalidates state at due window
                      │                                  (Invalidates if CAPTURED out-of-band)
                      │                                             │
                      └──────────────────────┬──────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ 5. EXECUTION & AUDIT PLANE (execution/, audit/, dashboard/)                             │
│    • Bounded Executor: Razorpay Adapter (Links, Status Checks) / Simulator              │
│    • Replay Flight Recorder: Emits 7-layer Decision Anatomy with contrastive rationales │
│    • Operations Console: Real-time telemetry, scenario lab, and benchmark analytics     │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### The 8-Stage Decision Anatomy Lifecycle

Every transaction processed by RecoveryOS moves sequentially through eight verifiable checkpoints:

$$\text{OBSERVE} \longrightarrow \text{DIAGNOSE} \longrightarrow \text{CANDIDATES} \longrightarrow \text{ECONOMIC SCORE} \longrightarrow \text{GOVERNOR} \longrightarrow \text{FIREWALL} \longrightarrow \text{EXECUTE} \longrightarrow \text{VERIFY}$$

---

## 5. System Components

| Plane | Component | Primary Responsibility | Key Modules |
| :--- | :--- | :--- | :--- |
| **Ingestion** | Ingestion Service | Validates HMAC signatures, deduplicates payloads, reconstructs state | `backend/api/webhooks.py`, `ingestion/` |
| **Context** | Recovery Memory | Attaches bounded merchant playbooks and sanitized historical telemetry | `rag/` |
| **Intelligence** | Diagnosis Provider | Infers root-cause archetype with calibrated uncertainty; deterministic fallback | `intelligence/`, `agent/agents.py` |
| **Decision** | Economic Policy | Generates Action $\times$ Timing matrix; optimizes expected net recovery | `policy/scoring.py`, `planner/timing.py` |
| **Safety** | Recovery Governor | Enforces merchant limits, cooldowns, human approval caps, and consent | `governor/recovery_governor.py` |
| **Safety** | Tool Firewall | Schema validation and payload boundary isolation; blocks malformed execution | `governor/firewall.py` |
| **Lifecycle** | Scheduler Service | Manages state-versioned delayed actions; invalidates stale executions | `scheduler/service.py` |
| **Execution** | Razorpay Adapter | Dispatches genuine payment links and reconciles gateway payment status | `execution/razorpay_adapter.py` |
| **Verification** | Reconciler | Re-evaluates payment state aggregate prior to execution | `ingestion/reconciler.py` |
| **Audit** | Replay Engine | Records 7-layer Decision Anatomy and contrastive *"Why We Acted"* audit logs | `audit/replay.py`, `audit/decision_log.py` |
| **Evaluation** | Benchmark Harness | Compares policies across multi-seed cohorts against counterfactual Oracle | `evaluation/harness.py`, `evaluation/` |

---

## 6. The Economic Decision Model

RecoveryOS treats revenue recovery as a constrained expected-value optimization problem under uncertainty. A high recovery probability alone is insufficient; an intervention must produce **positive incremental net yield** over what would happen if the merchant did nothing.

### Core Formulation

$$\mathbb{E}[\Delta Y_{\text{adj}}] = \text{Amount} \times \left( P(\text{recovery} \mid a) - P(\text{natural recovery}) \right) - C_{\text{action}}(a) - C_{\text{friction}}(a) - \text{Penalty}_{\text{churn}}(a)$$

Where:
- $\text{Amount}$: Transaction value in paise.
- $P(\text{recovery} \mid a)$: Estimated recovery probability under action $a$ at timing window $t$.
- $P(\text{natural recovery})$: Base probability that the customer resolves payment organically without outreach.
- $C_{\text{action}}(a)$: Direct marginal cost of intervention (e.g., ₹0.20 per gateway retry, ₹1.00 per SMS payment link).
- $C_{\text{friction}}(a)$: Customer annoyance and fatigue penalty accrued from outreach.
- $\text{Penalty}_{\text{churn}}(a)$: Expected lifetime value loss if intervention triggers customer opt-out or churn (modeled at ₹2,500 per churn event).

### Micro-Ticket Example: Why Abstention Wins

Consider a **₹1.00** failed payment on an expired card:
- **Option A (Blind Payment Link)**:
  $$\mathbb{E}[\text{Net}] = ₹1.00 \times 0.05 - ₹1.00 \text{ (Link Fee)} - ₹0.50 \text{ (Fatigue)} = -₹1.45 \quad \mathbf{(Value\ Destruction)}$$
- **Option B (RecoveryOS Abstention)**:
  $$\mathbb{E}[\text{Net}] = ₹0.00 \quad \mathbf{(Optimal\ Economic\ Choice)}$$

RecoveryOS selects `NO_ACTION`. Result: **₹0.00 spent, zero customer friction.**

---

## 7. Financial Safety by Design

The Large Language Model is isolated from financial authority.

```
       [ UNTRUSTED INPUT / TELEMETRY ]
                     │
                     ▼
         [ LLM DIAGNOSIS / STRATEGY ]  ───► Proposes Action Candidate
                     │
                     ▼
       [ DETERMINISTIC ECONOMIC SCORER ] ──► Calculates Expected Net Value
                     │
                     ▼
         [ RECOVERY GOVERNOR GATE ]    ───► Enforces Invariants (ALLOW / DENY / ABSTAIN)
                     │
                     ▼
           [ TOOL FIREWALL GATE ]      ───► Validates Schema & Consent Tokens
                     │
                     ▼
       [ BOUNDED DISPATCH / ADAPTER ]  ───► Executes Payment Link or Sim Action
```

### Non-Bypassable Safety Invariants

1. **Customer Consent Opt-Out**: If a customer has globally opted out of dunning communications, the Governor issues a hard `DENY` with reason code `CUSTOMER_OPTED_OUT`.
2. **Contact Limits ($24\text{h} / 7\text{d}$)**: Restricts customer outreach to a maximum of 2 contacts per 24 hours and 4 contacts per 7 days.
3. **Attempt Ceilings**: Enforces a strict maximum of 3 recovery attempts per transaction aggregate.
4. **Minimum Cooldown**: Enforces a minimum 4-hour cooldown between successive interventions.
5. **High-Value Escalation Threshold**: Any transaction exceeding ₹20,000 requiring non-standard outreach halts for human-in-the-loop review (`HUMAN_REVIEW_REQUIRED`).
6. **State-Versioned Idempotency**: Cryptographic hashes over webhook payloads prevent replay attacks and duplicate processing.
7. **Strict Fail-Closed Architecture**: If an external LLM provider encounters a network timeout or parsing failure, the engine fails closed with ₹0.00 dispatched.

---

## 8. State-Aware Recovery & Stale-Action Protection

Payment states are dynamic. A customer who failed payment at 10:00 AM may complete checkout independently at 10:30 AM via their mobile banking app.

```
10:00 AM  Payment fails (GATEWAY_TIMEOUT)
          └── RecoveryOS schedules delayed retry for +6h (State Version: V1)
10:30 AM  Customer pays organically out-of-band on merchant portal
          └── Razorpay emits webhook: payment.captured (State Version: V2)
          └── Ingestion Service reconciles payment aggregate to CAPTURED
04:00 PM  Scheduled execution window arrives (+6h)
          └── Scheduler revalidates aggregate before dispatch
          └── Expected State V1 != Current State V2 (CAPTURED)
          └── SCHEDULED ACTION INVALIDATED (₹0.00 spent, 0 duplicate debits)
```

RecoveryOS eliminates race conditions by coupling scheduled actions to aggregate state versions. Stale recovery actions are invalidated before dispatch.

---

## 9. Signature Demonstration Cases

All eight signature demonstration cases can be executed via CLI (`python scripts/demo.py`) or inspected inside the Operations Console (`/dashboard`):

| Case | Scenario & Amount | Inferred Diagnosis | Policy & Governor Verdict | Core Engineering Invariant Demonstrated |
| :---: | :--- | :--- | :---: | :--- |
| **01** | ₹1.00 Micro-ticket on expired card | `EXPIRED_PAYMENT_METHOD` | `NO_ACTION`<br>**`ABSTAIN`** | **Economic Abstention**: Avoids value destruction when intervention cost exceeds transaction value. |
| **02** | ₹5,000.00 Transient gateway error | `TRANSIENT_GATEWAY_FAILURE` | `RETRY_LATER (+6h)`<br>**`ALLOW`** | **Action $\times$ Timing**: Optimizes recovery yield across discrete timing windows. |
| **03** | ₹2,500.00 Organic out-of-band capture | `TRANSIENT_GATEWAY_FAILURE` | `RETRY_LATER`<br>**`INVALIDATED`** | **Stale-Action Protection**: Aggregate revalidation halts scheduled retries when payment is captured. |
| **04** | ₹1,000.00 Outreach to opted-out user | `INSUFFICIENT_FUNDS` | `REMINDER`<br>**`DENY`** | **Consent Governance**: Hard merchant policy halts outreach to globally opted-out customers. |
| **05** | 100-Scenario multi-archetype cohort | Mixed Distribution | `RECOVERYOS_DETERMINISTIC_V0` | **Cohort Benchmark**: Evaluates incremental net uplift and churn friction vs baselines. |
| **06** | ₹2,999.00 SaaS subscription drop | `MANDATE_ISSUE` | `PAYMENT_LINK`<br>**`ALLOW`** | **Subscription Recovery**: Direct payment link replaces failing auto-debit on revoked mandate. |
| **07** | ₹4,200.00 Cart drop at 3DS OTP | `CUSTOMER_ABANDONMENT` | `PAYMENT_LINK (+2h)`<br>**`ALLOW`** | **Checkout Drop-Off Recovery**: Delayed 1-click link avoids aggressive immediate dunning. |
| **08** | ₹3,500.00 Fatigued user during bank outage | `TRANSIENT_GATEWAY_FAILURE` | `RETRY_LATER`<br>**(Suboptimal Decision)** | **Regret Post-Mortem**: Transparently audits decision regret against counterfactual Oracle truth. |

---

## 10. Benchmark & Empirical Evaluation

> **Environment Label**: *Deterministic Synthetic Benchmark (100 Scenarios, Seed=42, Churn Penalty=₹2,500)*. Generated by `scripts/benchmark.py`.

### Policy Performance Comparison

| Policy | Gross Recovery | Action Costs | Churn Penalty | Adjusted Net Recovery | Incremental Net Uplift (★) | Actions | Avoided | Churned |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `baseline_0_no_action` | ₹21,040 | ₹0.00 | ₹0 | ₹21,040 | ₹0 | 0 | 100 | 0 |
| `baseline_1_always_retry` | ₹48,846 | ₹20.00 | ₹10,000 | ₹38,826 | +₹17,786 | 100 | 0 | 4 |
| `baseline_2_static_rules` | ₹122,709 | ₹74.40 | ₹27,500 | ₹95,135 | +₹74,095 | 100 | 0 | 11 |
| `baseline_3_probability_only`| ₹122,709 | ₹74.40 | ₹27,500 | ₹95,135 | +₹74,095 | 100 | 0 | 11 |
| **`RECOVERYOS_DETERMINISTIC_V0`** | ₹121,935 | **₹34.80** | **₹20,000** | **₹101,900** | **+₹80,860** | 94 | 6 | **8** |

### Benchmark Takeaways:
1. **+₹80,860 Incremental Adjusted Net Recovery**: Delivers a **+₹6,765 uplift** over static heuristics by factoring natural recovery and friction into decisioning.
2. **27% Churn Reduction**: Reduces churned customers from 11 down to 8 by eliminating spammy outreach on low-probability recoveries.
3. **53% Action Cost Reduction**: Cuts operational intervention costs from ₹74.40 to ₹34.80 through deliberate abstention.
4. **Theoretical Oracle Efficiency**: Achieves **48.6%** of theoretical Oracle upper-bound efficiency across 100 synthetic counterfactual scenarios with a **41.0% zero-regret rate**.

---

## 11. Razorpay Integration Scope

RecoveryOS integrates with Razorpay APIs while maintaining strict technical honesty regarding gateway boundaries:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                RAZORPAY INTEGRATION MATRIX                              │
├────────────────────────────────┬──────────────┬────────────────────────────────────────┤
│ Capability                     │ Status       │ Implementation Detail                  │
├────────────────────────────────┼──────────────┼────────────────────────────────────────┤
│ Webhook Ingestion & Deduplication│ REAL         │ HMAC SHA-256 constant-time digest      │
│ Payment State Reconciliation   │ REAL         │ GET /v1/payments/{id}                  │
│ Payment Link Creation          │ REAL         │ POST /v1/payment_links                 │
│ Event Sourcing Store           │ REAL         │ In-memory & SQLite event streams       │
│ Autonomous Card Network Retries│ SIMULATED    │ Models card retry timing & bank delay  │
│ Future Learned Bandit Uplift   │ SYNTHETIC    │ Synthetic priors calibrated per error  │
└────────────────────────────────┴──────────────┴────────────────────────────────────────┘
```

> **Fintech Honesty Boundary**: Under Reserve Bank of India (RBI) tokenization and two-factor authentication (2FA) guidelines, third-party software cannot autonomously execute unassisted debit transactions against customer credit/debit cards without an active e-mandate. RecoveryOS creates genuine Razorpay Payment Links and simulates delayed retry timing logic.

---

## 12. Observability, Replay & Audit

Every recovery decision produces an immutable, machine-readable audit record containing:
1. **Sanitized Observable Context**: Transaction parameters, payment method, error code, and contact counters.
2. **Diagnostic Assessment**: Failure archetype label and certainty score.
3. **Candidate Rankings**: Action $\times$ Timing evaluation matrix.
4. **Governor Invariants Trace**: Rule-by-rule evaluation results.
5. **Contrastive Rationales**:
   - **Why We Acted**: Expected marginal net yield exceeded action costs and friction.
   - **Why We Did Not Act**: Negative expected incremental recovery.
   - **Why Alternatives Were Rejected**: Evaluated alternative window produced lower net yield.

```json
{
  "case_id": "dec_sig_002",
  "payment_id": "pay_demo_02",
  "selected_action": "retry_later",
  "timing_window": "PLUS_6H",
  "expected_net_inr": 2749.80,
  "governor_decision": "ALLOW",
  "why_acted": "Delayed retry at +6h maximizes recovery probability (55%) after transient gateway failure.",
  "why_alternatives_rejected": {
    "retry_now": "Immediate retry probability (20%) too low during ongoing gateway degradation.",
    "payment_link": "Action cost (₹1.00) and friction higher than delayed background retry."
  }
}
```

---

## 13. Quickstart & Verification

### Prerequisites
- Python `>=3.11`
- Modern web browser (Chrome / Firefox / Brave)

### Installation & Setup

```bash
# 1. Clone repository
git clone https://github.com/dheerajgowd-18/recoveryOS.git
cd recoveryOS

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install package with development dependencies
pip install -e ".[dev]"
```

### Verification & Demonstration Commands

```bash
# Run full automated test suite (339 tests, 100% passing)
python -m pytest -q
# (or verbose mode: python -m pytest -v)

# Run signature 8-case CLI demonstration (< 5 seconds)
python scripts/demo.py

# Launch Operations Console Dashboard
uvicorn backend.app:app --host 127.0.0.1 --port 8000
# Open http://127.0.0.1:8000/dashboard in your browser

# Run 100-scenario multi-seed benchmark & sensitivity evaluation
python scripts/benchmark.py --scenarios 100 --seed 42 --no-holdout
```

---

## 14. Repository Structure

```
recoveryOS/
├── agent/            # State machine graph, runtime orchestrator, and reasoning agents
├── audit/            # Decision audit logging, flight-recorder, and case replay engine
├── backend/          # FastAPI application, webhook endpoints, and security middleware
├── dashboard/        # Operations Console UI (Jinja2, Tailwind CSS, Alpine.js)
├── domain/           # Core domain entities, payment states, events, and metrics
├── evaluation/       # Multi-seed benchmark runner, sensitivity grid, and baseline policies
├── execution/        # Bounded executors: Razorpay adapter and simulator executor
├── governor/         # Recovery Governor, Tool Firewall, and merchant policy invariants
├── ingestion/        # Webhook ingestion, event store, and payment state reconciler
├── intelligence/     # Diagnostic providers: Groq LLM integration and deterministic rules
├── planner/          # Action × Timing candidate generation and value estimation
├── policy/           # Deterministic recovery policies, scoring, and candidate ranking
├── rag/              # Bounded recovery memory and merchant playbook retrieval
├── scheduler/        # State-versioned lifecycle store and stale-action scheduler
├── simulator/        # Synthetic payment failure generator and potential outcomes
├── scripts/          # CLI utilities: demo runner and multi-seed benchmark harness
└── tests/            # Automated test suite (339 tests: unit, integration, adversarial)
```

---

## 15. Scope Boundaries & Current Limitations

1. **Synthetic Benchmark Environment**: The current evaluation harness measures performance against synthetic counterfactual potential outcomes ($Y(a)$) and parameterized priors. It does not claim live production randomized controlled trial (RCT) results.
2. **Discrete Timing Grid**: Timing optimization evaluates five discrete windows (`IMMEDIATE`, `PLUS_2H`, `PLUS_6H`, `PLUS_12H`, `PLUS_24H`) rather than continuous real-time customer payday estimation.
3. **Single-Node Operations Console**: The Operations Console is optimized for local demonstration and evaluation. Enterprise SAML/SSO authentication and multi-tenant RBAC are out of scope for this prototype.
4. **Gateway Execution**: Card network auto-debits are modeled through simulation; live Razorpay integration dispatches genuine payment links via `POST /v1/payment_links` and reconciles status via `GET /v1/payments/{id}`.

---

## 16. Engineering Roadmap

- [x] Authoritative 10-node stateful runtime DAG (`agent/graph.py`)
- [x] Action $\times$ Timing discrete economic optimization (`planner/timing.py`)
- [x] Non-bypassable Recovery Governor and Tool Firewall (`governor/`)
- [x] State-versioned scheduling and stale-action invalidation (`scheduler/`)
- [x] Razorpay HMAC SHA-256 webhook verification & payment-link creation (`execution/`)
- [x] 8-case signature demonstration suite (`scripts/demo.py`)
- [x] Full automated test suite (339 tests passing, 0 failures)
- [ ] Multi-armed contextual bandit models for learned real-world uplift
- [ ] Integration with Razorpay Subscriptions Autopay e-mandate execution APIs
- [ ] Distributed event sourcing backends (CockroachDB / PostgreSQL)

---

## 17. Razorpay AI Buildathon 2026 Submission

- **Repository**: [https://github.com/dheerajgowd-18/recoveryOS](https://github.com/dheerajgowd-18/recoveryOS)
- **Track**: Track 03 — AI Revenue Recovery
- **Verified Commit**: `1ce98a71e72f00182533d6e16dcb89125b19ee72`
- **Verification Result**: 339 / 339 tests passing (`pytest -q`), clean checkout reproducible.
