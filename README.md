# RecoveryOS: Autonomous AI Revenue Recovery Agent

[![Build Status](https://img.shields.io/badge/tests-89%20passed-brightgreen.svg)]()
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![Pydantic Version](https://img.shields.io/badge/pydantic-v2-orange.svg)]()
[![Razorpay AI Buildathon 2026](https://img.shields.io/badge/Track%2003-AI%20Revenue%20Recovery-blueviolet.svg)]()

> **Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery**
>
> **The North Star Metric**: Maximize **Incremental Adjusted Net Recovery** ($\Delta Y_{\text{adj}} = Y(a) - Y(\text{no\_action}) - \text{Action Costs} - \text{Churn Penalty}$) while eliminating value-destructive interventions, contact fatigue, and customer churn.

---

## 1. Executive Summary & Benchmark Results

Traditional subscription dunning systems rely on static retry schedules and aggressive payment link broadcasting. In fintech billing environments, these naive heuristics destroy customer goodwill, trigger gateway surcharge fees on impossible recoveries (e.g. expired cards), and take credit for transactions that would have naturally resolved on their own.

**RecoveryOS** introduces a closed-loop, state-reconciling autonomous recovery agent protected by a strict **Public Policy Boundary**, a **Tool Firewall**, and a transparent **Expected-Value Proxy Scorer**.

### Benchmark Comparison (100 Deterministic Synthetic Scenarios, Seed=42)

*Evaluated with a conservative customer churn friction penalty of ₹2,500 per churned customer.*

| Policy Benchmark | Gross Recovery | Action Costs | Churn Penalty | Adjusted Net Recovery | Incremental Adjusted Net | Interventions | Actions Avoided | Churned Customers |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline 0: No Action** (Natural Baseline) | ₹21,040 | ₹0.00 | ₹0 | ₹21,040 | ₹0 | 0 | 100 | 0 |
| **Baseline 1: Always Retry** (Naive Gateway) | ₹48,846 | ₹20.00 | ₹10,000 | ₹38,826 | ₹17,786 | 100 | 0 | 4 |
| **Baseline 2: Static Rules** (Heuristic Dunning) | ₹122,709 | ₹74.40 | ₹27,500 | ₹95,135 | ₹74,095 | 100 | 0 | 11 |
| **Baseline 3: Probability Only** (Greedy Model) | ₹122,709 | ₹74.40 | ₹27,500 | ₹95,135 | ₹74,095 | 100 | 0 | 11 |
| **RecoveryOS (Deterministic v0)** | **₹121,935** | **₹36.00** | **₹20,000** | **₹101,899** | **₹80,859** | **96** | **4** | **8** |

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
                     |       domain/aggregates.py        |
                     |  - PaymentAggregate               |
                     |  - SubscriptionAggregate          |
                     +-----------------+-----------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                        CLOSED-LOOP AGENT RUNTIME (agent/)                         |
|                                                                                   |
|  [RiskDetector] -> High Risk Detected                                             |
|        |                                                                          |
|        v                                                                          |
|  [PublicScenarioView Boundary] (Zero Leakage of Archetypes or Potential Outcomes) |
|        |                                                                          |
|        v                                                                          |
|  [DeterministicRecoveryPolicy]                                                    |
|    - CandidateGenerator: Physical failure constraints & attempt caps              |
|    - ExpectedValueScorer: Net Economic Uplift Proxy Scoring                       |
|        |                                                                          |
|        +-----------------------------> [NO_ACTION] --------> [Halt / Abstain]     |
|        |                                                                          |
|        v [Active Action Candidate]                                                |
|  [Stale Action Revalidation Check] (Cancels retry if captured out-of-band)        |
|        |                                                                          |
|        v                                                                          |
|  [ToolFirewall]                                                                   |
|    - Schema Validation                                                            |
|    - Customer Opt-Out / Consent Verification                                      |
|    - Action Idempotency Lock                                                      |
|        |                                                                          |
|        v (Gated Action)                                                           |
|  [RecoveryExecutor / SimulatorExecutor]                                           |
|        |                                                                          |
|        v (Emits payment.captured / payment.failed event)                          |
|  [IngestionService.process_webhook()] -> Mutates Reconciled Aggregate State       |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
                     +-----------------------------------+
                     |         audit/replay.py           |
                     |  - DecisionRecord Provenance      |
                     |  - ReplayEngine Reconstruction    |
                     +-------------------+
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

# 2. Run automated test suite (104 passing tests)
python -m pytest -v

# 3. Run signature CLI demonstration
python scripts/demo.py
```

The CLI demo proves the 5 core behavioral pillars:
1. **Correct Abstention**: Rejects negative net value dunning on low-value transactions.
2. **Delayed Retry Economic Selection**: Compares candidate interventions and chooses `RETRY_LATER` based on expected net value.
3. **Late State Revalidation**: Detects out-of-band organic captures and cancels pending retries.
4. **Safety Governance**: Blocks contact actions for opted-out customers via `ToolFirewall`.
5. **Batch Benchmark**: Runs full comparative evaluation across 100 deterministic scenarios with churn penalties.

---

## 4. Documentation Directory

- [ARCHITECTURE.md](ARCHITECTURE.md) — Deep-dive architecture and component mechanics.
- [EVALUATION.md](EVALUATION.md) — Evaluation methodology, benchmark baselines, and counterfactual metrics.
- [ASSUMPTIONS.md](ASSUMPTIONS.md) — Complete modeling assumptions, action costs, and simulation constraints.
- [LIMITATIONS.md](LIMITATIONS.md) — Transparent assessment of technical boundaries and production requirements.
- [THREAT_MODEL.md](THREAT_MODEL.md) — Complete security architecture, threat matrix, and fail-closed mitigations.
- [DEMO.md](DEMO.md) — Interactive CLI demonstration guide and judges' walkthrough.
- [PITCH.md](PITCH.md) — 5-minute panel pitch script and defense Q&A.
- [CHANGELOG.md](CHANGELOG.md) — Chronological release history (v0.1.0 to v0.8.0).
