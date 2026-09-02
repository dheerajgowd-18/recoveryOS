# RecoveryOS: Autonomous AI Revenue Recovery Agent

[![Build Status](https://img.shields.io/badge/tests-209%20passed-brightgreen.svg)]()
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)]()
[![Pydantic Version](https://img.shields.io/badge/pydantic-v2-orange.svg)]()
[![Razorpay AI Buildathon 2026](https://img.shields.io/badge/Track%2003-AI%20Revenue%20Recovery-blueviolet.svg)]()
[![LLM Provider](https://img.shields.io/badge/LLM-Groq%20llama--3.3--70b--versatile-indigo.svg)]()

> **Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery**
>
> **Core Architectural Rule**: *The model proposes. The Governor authorizes. The executor acts.*
>
> **The North Star Metric**: Maximize **Incremental Adjusted Net Recovery** ($\Delta Y_{\text{adj}} = Y(a) - Y(\text{no\_action}) - \text{Action Costs} - \text{Churn Penalty}$) while eliminating value-destructive interventions, contact fatigue, and customer churn.

---

## 1. Executive Summary & Operations Console

Traditional subscription dunning systems rely on static retry schedules and aggressive payment link broadcasting. In fintech billing environments, these naive heuristics destroy customer goodwill, trigger gateway surcharge fees on impossible recoveries (e.g. expired cards), and take credit for transactions that would have naturally resolved on their own.

**RecoveryOS** introduces a closed-loop, state-reconciling autonomous recovery agent built on four strict separation-of-concern planes:
1. **Memory & Context Plane**: Bounded context assembler and Recovery Memory RAG (`rag/`) attaching immutable provenance metadata without exposing simulator ground truth.
2. **Intelligence Plane**: Specialized Multi-Agent reasoning graph (`agent/agents.py`, `agent/graph.py`) powered by real open-weights LLM (`Groq llama-3.3-70b-versatile`) and deterministic offline diagnostic providers.
3. **Governance Plane**: Recovery Governor v1 with deterministic mathematical scoring, contact fatigue caps, and an independent fail-closed Tool Firewall.
4. **Execution Plane**: Scheduled action lifecycle service with stale-action state versioning, a high-density Operations Console (`GET /dashboard`) featuring an interactive 6-case Scenario Lab (`POST /dashboard/api/scenarios/{id}/run`), and a secure Razorpay test-mode adapter and live webhook gateway (`POST /webhooks/razorpay`).

### Benchmark Comparison (100 Deterministic Synthetic Scenarios, Seed=42)

*Evaluated with a conservative customer churn friction penalty of ₹2,500 per churned customer.*

| Policy Benchmark | Gross Recovery | Action Costs | Churn Penalty | Adjusted Net Recovery | Incremental Adjusted Net | Interventions | Actions Avoided | Churned Customers |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline 0: No Action** (Natural Baseline) | ₹21,040 | ₹0.00 | ₹0 | ₹21,040 | ₹0 | 0 | 100 | 0 |
| **Baseline 1: Always Retry** (Naive Gateway) | ₹48,846 | ₹20.00 | ₹10,000 | ₹38,826 | ₹17,786 | 100 | 0 | 4 |
| **Baseline 2: Static Rules** (Heuristic Dunning) | ₹122,709 | ₹74.40 | ₹27,500 | ₹95,135 | ₹74,095 | 100 | 0 | 11 |
| **Baseline 3: Probability Only** (Greedy Model) | ₹122,709 | ₹74.40 | ₹27,500 | ₹95,135 | ₹74,095 | 100 | 0 | 11 |
| **RecoveryOS (Deterministic v0)** | **₹121,935** | **₹36.00** | **₹20,000** | **₹101,899** | **₹80,859** | **96** | **4** | **8** |
| **RecoveryOS (Groq LLM-Driven)** | **₹121,935** | **₹36.00** | **₹20,000** | **₹101,899** | **₹80,859** | **96** | **4** | **8** |

### Why RecoveryOS Outperforms Baselines
1. **Beats All Baselines on North Star Metric**: Delivers **₹80,859** in Incremental Adjusted Net Recovery (+₹6,764 over Static Rules and Greedy Probability baselines, and +₹63,073 over Always Retry).
2. **27% Reduction in Customer Churn**: Preserves customer lifetime value (LTV) by replacing aggressive link spam with optimal timed retries (8 churned customers vs 11 under Static Rules).
3. **52% Reduction in Action Execution Costs**: Avoids expensive redundant communications (₹36.00 total action costs vs ₹74.40 under Static Rules).
4. **Intelligent Abstention (4 Actions Avoided)**: Evaluates expected net value and safely abstains on micro-transactions where dunning costs exceed expected recovery.

---

## 2. System Architecture

```
                       +-------------------------------+
                       |   Razorpay Webhook Dispatch   |
                       +---------------+---------------+
                                       |
                                       | POST /webhooks/razorpay
                                       v
                     +-----------------------------------+
                     | backend/dependencies/security.py  |
                     |  - Raw HMAC SHA-256 Verification  |
                     |  - Constant-time compare_digest   |
                     +-----------------+-----------------+
                                       |
                                       v
                     +-----------------------------------+
                     | backend/services/ingestion_service|
                     |  - Idempotent Event Deduplication |
                     |  - Append-Only Event Store        |
                     |  - StateReconciler State Machine  |
                     +-----------------+-----------------+
                                       |
                                       v
                     +-----------------------------------+
|                        CLOSED-LOOP AGENT RUNTIME (agent/)                         |
|                                                                                   |
|  [RiskDetector] -> Payment Risk Detected                                          |
|        |                                                                          |
|        v                                                                          |
|  [ObservableRecoveryContext] (Strict Hidden/Public Boundary: No Hidden Truth)     |
|        |                                                                          |
|        v                                                                          |
|  [Structured Intelligence Layer] (intelligence/)                                  |
|    - GroqLLMDiagnosisProvider (llama-3.3-70b-versatile via Groq SDK with JSON mode)|
|    - DeterministicDiagnosisProvider (Fail-Closed Offline Rule Fallback)           |
|    - StructuredDiagnosis: taxonomy label, confidence, evidence, timing hint       |
|        |                                                                          |
|        v                                                                          |
|  [DeterministicRecoveryPolicy & Action x Timing Planner] (planner/timing.py)      |
|    - Low Confidence Gate: Abstains if diagnosis confidence < threshold            |
|    - TimingCandidateGenerator: Admissible (Mechanism x Timing Window) pairs      |
|    - DeterministicTimingValueEstimator: Expected Net Value across discrete windows|
|        |                                                                          |
|        v [Proposed Action x Timing Candidate]                                     |
|  [Recovery Governor v1] (governor/recovery_governor.py)                           |
|    - Validates: Recovery Window Bound, Cooldowns, Contact Limits, Consent, Caps   |
|    - Outcomes: ALLOW, DENY, DEFER, ESCALATE, ABSTAIN                              |
|        |                                                                          |
|        +---- [DENY / DEFER / ESCALATE / ABSTAIN] ----> [Halt / Human Review Trace] |
|        |                                                                          |
|        v [ALLOW]                                                                  |
|        +-----------------------------------+----------------------------------+   |
|        | (Immediate Timing Window)         | (Delayed Timing Window)          |   |
|        v                                   v                                  |   |
|  [ToolFirewall Pre-Check]            [ScheduledLifecycleService (scheduler/)] |   |
|        |                               - Persists ScheduledAction (State vN)  |   |
|        |                               - Exits Loop: ACTION_SCHEDULED         |   |
|        |                                   |                                  |   |
|        |                                   v (When Due / On Trigger)          |   |
|        |                             [Pre-Execution State Revalidation]       |   |
|        |                               - Validates current aggregate version  |   |
|        |                               - If Terminal/Captured: INVALIDATE     |   |
|        |                               - If Window Exceeded: EXPIRE           |   |
|        |                               - Else: Passes through ToolFirewall    |   |
|        |                                   |                                  |   |
|        +-----------------------------------+                                  |   |
|        v                                                                          |   |
|  [ToolFirewall] (governor/firewall.py - Independent Safety & Idempotency Gate)    |   |
|    - Schema Validation                                                            |   |
|    - Channel Consent Double-Check                                                 |   |
|    - Action Idempotency Lock                                                      |   |
|        |                                                                          |   |
|        v (Gated Action)                                                           |   |
|  [RecoveryExecutor / SimulatorExecutor]                                           |   |
|        |                                                                          |   |
|        v (Emits payment.captured / payment.failed event)                          |   |
|  [IngestionService.process_webhook()] -> Mutates Reconciled Aggregate State       |   |
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

## 3. Quickstart & Verification

### Standard Make Workflow
```bash
make install    # Installs dependencies via pip install -r requirements.txt
make test       # Runs the complete automated test suite (python -m pytest -v)
make demo       # Runs the 5 signature demo cases CLI showcase (python scripts/demo.py)
```

### Direct Python Fallback (If `make` is unavailable)
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run automated test suite (176 passing tests)
python -m pytest -v

# 3. Launch the Operations Console Dashboard
uvicorn backend.app:app --host 127.0.0.1 --port 8000
# Open http://127.0.0.1:8000/dashboard in your browser

# 4. Run signature CLI demonstration (Fast 100-scenario showcase)
python scripts/demo.py

# 5. Run Expanded Evaluation Lab (Multi-seed 5,000 scenario benchmark with holdout & oracle regret)
python scripts/benchmark.py --scenarios 1000 --seeds 42,43,44 --holdout-seeds 45,46
```

### Operations Console Interface (`GET /dashboard`)
The RecoveryOS Operations Console provides a production-grade, dark-themed merchant cockpit built with FastAPI, Jinja2, Tailwind CSS, and Alpine.js (zero Node.js build dependencies):
1. **Merchant Control Room**: Executive KPI strip displaying Revenue at Risk, Gross Recovered, Incremental Net Recovery, Interventions Avoided, and real-time event telemetry.
2. **Recovery Queue**: Operational queue of active failure cohorts ranked by priority and expected incremental value.
3. **Case Decision Replay**: Deep chronological audit trace reconstructing exact step-by-step reasoning ("Why We Acted" vs "Why We Did Not Act").
4. **Evaluation Lab**: Interactive multi-seed statistical proof, baseline comparisons, Oracle hindsight ceiling, regret bounds, and sensitivity grid.
5. **Exceptions & Audit**: Surveillance of stale action invalidations, consent opt-outs, and human review escalations.

---

## 4. Documentation Directory

- [ARCHITECTURE.md](ARCHITECTURE.md) — Deep-dive architecture, Action × Timing model, and Scheduled Lifecycle mechanics.
- [EVALUATION.md](EVALUATION.md) — Evaluation methodology, benchmark baselines, and counterfactual metrics.
- [ASSUMPTIONS.md](ASSUMPTIONS.md) — Complete modeling assumptions, action costs, and simulation constraints.
- [LIMITATIONS.md](LIMITATIONS.md) — Transparent assessment of technical boundaries and production requirements.
- [THREAT_MODEL.md](THREAT_MODEL.md) — Complete security architecture, threat matrix, and fail-closed mitigations.
- [DEMO.md](DEMO.md) — Interactive CLI demonstration guide and judges' walkthrough.
- [PITCH.md](PITCH.md) — 5-minute panel pitch script and defense Q&A.
- [CHANGELOG.md](CHANGELOG.md) — Chronological release history (v0.1.0 to v1.6.0).
