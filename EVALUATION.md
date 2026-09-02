# RecoveryOS Evaluation Methodology & Benchmark Specification

---

## 1. Evaluation Philosophy: Why Incremental Adjusted Net Recovery Matters

In subscription billing and dunning systems, naive evaluation metrics like **Gross Recovery** are deceptive. A substantial portion of failed payments resolve organically without any intervention (e.g. natural customer deposits, payday timing, background bank clearance). When an automated system executes an intervention on a customer who would have recovered naturally:
1. It takes credit for revenue it did not cause.
2. It incurs avoidable gateway API fees or messaging costs.
3. It increases customer contact fatigue and churn probability.

**RecoveryOS** evaluates policies using a **Counterfactual Potential Outcome Framework** $Y(a)$ adjusted for execution costs and customer churn penalties:
$$\text{Net Recovery} = \text{Gross Recovery} - \text{Total Action Cost}$$
$$\text{Adjusted Net Recovery} = \text{Gross Recovery} - \text{Total Action Cost} - \text{Churn Penalty}$$
$$\text{Incremental Adjusted Net Recovery} = \text{Adjusted Net}(\text{Policy}) - \text{Adjusted Net}(\text{Baseline 0: No Action})$$

---

## 2. Important Disclosure Regarding Synthetic Evaluation

> **Methodological Disclosure (Master Plan Section 50)**:
> The evaluation metrics and benchmark tables presented in this repository are computed using a controlled, deterministic **Synthetic Revenue-Recovery Simulator** (`simulator/`).
>
> While the synthetic environment faithfully implements realistic behavioral archetypes, Razorpay error codes, and physical failure constraints, **synthetic simulations do not constitute empirical proof of live production causal uplift**. In a live deployment, real-world customer response probabilities, churn elasticity, and customer lifetime value (LTV) must be verified through randomized controlled trials (A/B testing) with stratified merchant cohorts.

---

## 3. Benchmark Baseline Policies

The evaluation harness benchmarks RecoveryOS against 4 standard industry baselines:

1. **Baseline 0: No Action (`NoActionPolicy`)**
   - Policy: Always abstains from intervention ($a = \text{NO\_ACTION}$).
   - Purpose: Measures the organic **Natural Recovery Baseline** $Y(\text{no\_action})$ across the customer cohort.
2. **Baseline 1: Always Retry (`AlwaysRetryPolicy`)**
   - Policy: Unconditionally triggers an immediate retry ($a = \text{RETRY\_NOW}$) upon every failure.
   - Purpose: Represents naive gateway dunning without error classification or delay optimization.
3. **Baseline 2: Static Rule Dunning (`StaticRulePolicy`)**
   - Policy: Heuristic branching mapping error codes to hardcoded actions (e.g., `GATEWAY_ERROR` -> `RETRY_NOW`, `INSUFFICIENT_FUNDS` -> `PAYMENT_LINK`).
   - Purpose: Represents typical legacy dunning rule engines.
4. **Baseline 3: Probability-Only Maximizer (`ProbabilityOnlyPolicy`)**
   - Policy: Selects the action with highest raw estimated recovery probability:
     $$a^* = \arg\max_a P(a \mid x)$$
   - Purpose: Represents naive ML models that ignore action costs and customer fatigue.
5. **RecoveryOS Deterministic v0 (`DeterministicRecoveryPolicy`)**
   - Policy: Receives/infers structured diagnosis from observable evidence, filters candidate actions under physical failure constraints, estimates net incremental recovery uplift allowing negative uplift ($\Delta P < 0$), and enforces net value thresholds and abstention guards:
     $$a^* = \arg\max_{a \in \mathcal{A}_{\text{admissible}}} \left( \text{Amount} \times (P(a) - P(\text{no\_action})) - \text{Cost}(a) \right)$$
6. **RecoveryOS Groq LLM-Driven (`LLMDrivenRecoveryPolicy`)**
   - Policy: Uses `GroqLLMDiagnosisProvider` (`openai/gpt-oss-120b` with JSON schema enforcement) to infer structured root causes, passing candidate actions to the Action × Timing planner and Recovery Governor. Available in benchmark via `--compare-llm`.

---

## 4. Metric Definitions & Mathematical Formulas

| Metric Name | Mathematical Formula | Description |
| :--- | :--- | :--- |
| **Gross Recovery** | $\sum Y(a_{\text{chosen}})$ | Total revenue captured across all scenarios |
| **Natural Recovery** | $\sum Y(\text{no\_action})$ | Revenue captured organically without intervention |
| **Incremental Uplift** | $\sum [Y(a_{\text{chosen}}) - Y(\text{no\_action})]$ | Net revenue directly caused by intervention |
| **Action Costs** | $\sum \text{Cost}(a_{\text{chosen}})$ | Total execution fees and SMS/WhatsApp link costs |
| **Churn Penalty** | $\sum \mathbb{I}(\text{Churned}) \times \text{Penalty}$ | Economic penalty assigned per churned customer (₹2,500 proxy) |
| **Adjusted Net Recovery** | $\text{Gross Recovery} - \text{Action Costs} - \text{Churn Penalty}$ | Net recovered revenue minus direct costs and churn friction |
| **Incremental Adjusted Net** | $\text{Adjusted Net}(\text{Policy}) - \text{Adjusted Net}(\text{Baseline 0})$ | True north-star economic recovery uplift over natural baseline |
| **Interventions** | $\sum \mathbb{I}(a_{\text{chosen}} \neq \text{NO\_ACTION})$ | Total active dunning interventions triggered |
| **Actions Avoided** | $\sum \mathbb{I}(a_{\text{chosen}} = \text{NO\_ACTION})$ | Total scenarios where the policy safely abstained |
| **Customer Churn Count** | $\sum \mathbb{I}(\text{Churned})$ | Number of customers who permanently churned due to dunning fatigue |
| **Diagnosis Accuracy** | $\frac{1}{N}\sum \mathbb{I}(\hat{D} = D^*)$ | Evaluator-side accuracy of inferred diagnosis vs hidden root cause |
| **Fallback Count** | $\sum \mathbb{I}(\text{Source} = \text{fallback})$ | Invocations safely fallen back to deterministic offline rules |
| **Governor Allowed** | $\sum \mathbb{I}(\text{Gov} = \text{ALLOW})$ | Total proposed actions approved by the Recovery Governor |
| **Governor Denied** | $\sum \mathbb{I}(\text{Gov} = \text{DENY})$ | Total proposed actions blocked by merchant policies or limits |
| **Governor Deferred** | $\sum \mathbb{I}(\text{Gov} = \text{DEFER})$ | Total actions postponed due to active cooldown windows |
| **Human Escalations** | $\sum \mathbb{I}(\text{Gov} = \text{ESCALATE})$ | Total high-value or ambiguous cases routed to human review |
| **Governor Abstentions** | $\sum \mathbb{I}(\text{Gov} = \text{ABSTAIN})$ | Total zero-intervention baseline decisions confirmed |
| **Actions Scheduled** | $\sum \mathbb{I}(\text{Timing} \neq \text{IMMEDIATE})$ | Total actions persisted into the scheduled action lifecycle |
| **Immediate Actions** | $\sum \mathbb{I}(\text{Timing} = \text{IMMEDIATE})$ | Total actions executed immediately without delay |
| **Scheduled Invalidated** | $\sum \mathbb{I}(\text{Status} = \text{INVALIDATED})$ | Total scheduled actions canceled pre-execution due to organic capture |
| **Scheduled Expired** | $\sum \mathbb{I}(\text{Status} = \text{EXPIRED})$ | Total scheduled actions expired past the recovery window |

---

## 5. Benchmark Performance Comparison (100 Scenarios, Seed=42)

*Generated by `python scripts/demo.py` under `DEFAULT_CHURN_PENALTY_PAISE_PER_CUSTOMER = 250_000` (₹2,500).*

```
-------------------------------------------------------------------------------------------------------------------
Policy                       | Gross Recov | Cost       | Churn Pen  | Adj Net      | Incr Adj Net | Acts  | Avoid | Churn
-------------------------------------------------------------------------------------------------------------------
baseline_0_no_action         | INR 21,040  | INR 0.00   | INR 0      | INR 21,040   | INR 0        | 0     | 100   | 0    
baseline_1_always_retry      | INR 48,846  | INR 20.00  | INR 10,000 | INR 38,826   | INR 17,786   | 100   | 0     | 4    
baseline_2_static_rules      | INR 122,709 | INR 74.40  | INR 27,500 | INR 95,135   | INR 74,095   | 100   | 0     | 11   
baseline_3_probability_only  | INR 122,709 | INR 74.40  | INR 27,500 | INR 95,135   | INR 74,095   | 100   | 0     | 11   
RECOVERYOS_DETERMINISTIC_V0  | INR 121,935 | INR 36.00  | INR 20,000 | INR 101,899  | INR 80,859   | 96    | 4     | 8    
-------------------------------------------------------------------------------------------------------------------

  GOVERNOR & SCHEDULER OPERATIONAL AUDIT COUNTERS:
--------------------------------------------------------------------------------------------------------------
Policy                       | Gov Allow | Gov Deny | Gov Abstain | Gov Defer | Human Review | Scheduled | Immediate
--------------------------------------------------------------------------------------------------------------
baseline_0_no_action         | 0         | 0        | 100         | 0         | 0            | 0         | 0
baseline_1_always_retry      | 100       | 0        | 0           | 0         | 0            | 0         | 100
baseline_2_static_rules      | 100       | 0        | 0           | 0         | 0            | 0         | 100
baseline_3_probability_only  | 100       | 0        | 0           | 0         | 0            | 0         | 100
RECOVERYOS_DETERMINISTIC_V0  | 96        | 0        | 4           | 0         | 0            | 75        | 21
--------------------------------------------------------------------------------------------------------------
```

### Key Benchmark Takeaways
1. **North-Star Superiority**: RecoveryOS delivers **₹80,859** in Incremental Adjusted Net Recovery, outperforming Static Rules (₹74,095) by **+₹6,764** and Always Retry (₹17,786) by **+₹63,073**.
2. **27% Lower Customer Churn**: RecoveryOS reduces customer churn from 11 churned customers down to 8 by eliminating spammy payment links on transient failures.
3. **52% Action Cost Savings**: RecoveryOS incurs only ₹36.00 in execution costs compared to ₹74.40 under static rule heuristics.
4. **Active Abstention (4 Avoided Actions)**: Correctly identifies micro-transactions with negative expected net recovery and refrains from wasteful dunning.
5. **Operational Timing Optimization**: RecoveryOS schedules 75 delayed retries at high-success windows (e.g. +6h) while executing 21 immediate actions only when justified.

---

## 6. Expanded Evaluation Lab & Multi-Seed Methodology

To eliminate sample bias and satisfy the Master Build Plan requirements for **batch proof**, RecoveryOS provides an expanded multi-seed benchmark runner (`evaluation/benchmark_runner.py`, `scripts/benchmark.py`).

### Multi-Seed Statistical Aggregation
Single-seed evaluations can be subject to random variance in scenario sampling. The multi-seed runner generates independent cohorts across a defined seed list, running all policies and computing sample standard deviation and 95% Confidence Intervals:
$$\text{CI}_{95\%} = \bar{X} \pm 1.96 \cdot \frac{s}{\sqrt{N}}$$

### Running the Evaluation Suite
```bash
# Standard 5-baseline comparative benchmark
python scripts/benchmark.py --scenarios 100 --seeds 42,43,44,45,46

# Benchmark including Groq LLM-driven policy comparison
python scripts/benchmark.py --scenarios 100 --seed 42 --compare-llm
```

---

## 7. Development vs. Holdout Dataset Split

To prevent overfitting heuristic priors or policy parameters, the benchmark runner supports explicit split segregation:

| Split Name | Seed Range | Purpose | Usage In Policy Tuning |
| :--- | :--- | :--- | :--- |
| **Development Set** | Seeds `42, 43, 44` (3,000 scenarios) | Hyperparameter calibration, timing curve tuning | Permitted |
| **Holdout Set** | Seeds `45, 46` (2,000 scenarios) | Generalization verification on unseen scenarios | **Strictly Prohibited (Frozen)** |
| **Combined Cohort** | Seeds `42–46` (5,000 scenarios) | Full population statistical benchmark & reports | Summary reporting |

---

## 8. Theoretical Counterfactual Oracle Benchmark

The **Oracle Policy** (`evaluation/oracle.py`) acts as a diagnostic mathematical upper bound. It possesses perfect evaluator-side hindsight of the secret counterfactual potential outcome vector $Y(a)$ and selects the action maximizing incremental adjusted net recovery over the organic baseline:
$$a^* = \arg\max_{a \in \mathcal{A}} \left[ \text{AdjustedNet}(a) - \text{AdjustedNet}(\text{NO\_ACTION}) \right]$$

### Efficiency & Gap Metrics
- **Oracle Incremental Adjusted Net**: Theoretical maximum possible incremental net recovery over $Y(\text{no\_action})$ ($\ge 0$).
- **RecoveryOS Incremental Adjusted Net**: Realized incremental adjusted net recovery over natural recovery.
- **Incremental Gap**: $\text{Oracle Incremental Adjusted Net} - \text{RecoveryOS Incremental Adjusted Net}$.
- **Oracle Efficiency %**: $\frac{\text{RecoveryOS Incremental Adjusted Net}}{\text{Oracle Incremental Adjusted Net}} \times 100\%$.

> [!NOTE]
> The Oracle is never exposed to the agent or policy runtime. It is strictly evaluated post-hoc by the evaluation harness.

---

## 9. Decision Regret Calculation & Exact Mathematical Reconciliation

For each scenario $i$, decision regret is computed evaluator-side against the optimal counterfactual choice:
$$\text{Regret}_i = \text{OracleIncrementalAdjustedNet}_i - \text{ChosenIncrementalAdjustedNet}_i \ge 0$$

Because the natural baseline is identical for both terms within scenario $i$:
$$\text{Regret}_i = \text{RealizedAdjustedNet}(\text{OracleAction}_i) - \text{RealizedAdjustedNet}(\text{ChosenAction}_i)$$

### Exact Population Reconciliation Identity
Summing across all evaluated scenarios $i=1 \dots N$:
$$\text{Total Regret} = \sum_{i=1}^N \text{Regret}_i = \sum_{i=1}^N \text{OracleIncrNet}_i - \sum_{i=1}^N \text{ChosenIncrNet}_i \equiv \text{Incremental Gap}$$
$$\text{Mean Regret} = \frac{\text{Total Regret}}{N} = \frac{\text{Incremental Gap}}{N}$$

The evaluation lab computes:
- **Total Regret**: Cumulative economic value left on the table across the entire cohort (identically equals the Incremental Gap).
- **Mean Regret** ($\bar{R}$): Average regret in paise per scenario.
- **Median Regret**: Robust median measure of decision friction.
- **P95 Regret ($P_{95}$)**: 95th percentile tail risk and failure bound.
- **Zero-Regret Rate**: Proportion of scenarios where RecoveryOS made the bit-identical optimal choice to the Oracle.

---

## 10. Multi-Parameter Economic Sensitivity Matrix

To prove robustness across different business models and cost regimes, the sensitivity engine (`evaluation/sensitivity.py`) performs a grid sweep across:
- **Churn Friction Penalties**: ₹1,000, ₹2,500, ₹5,000 per churned customer.
- **Action Cost Multipliers**: $0.5\times$ (low gateway fees), $1.0\times$ (standard), $2.0\times$ (high fees/surcharges).

For each cell in the grid, the analyzer recalculates net economics and verifies whether RecoveryOS maintains superior incremental adjusted net recovery over all baseline benchmarks (`recoveryos_wins_bool`).

---

## 11. CLI Execution Guide

### Fast 100-Scenario Interactive Showcase
```bash
python scripts/demo.py
```

### Multi-Seed Development & Holdout Benchmark (5,000 Scenarios)
```bash
python scripts/benchmark.py --scenarios 1000 --seeds 42,43,44 --holdout-seeds 45,46
```

### Single Seed Benchmark
```bash
python scripts/benchmark.py --scenarios 100 --seed 42
```
