# RecoveryOS Signature Showcase & Interactive Demo Guide

This document outlines the step-by-step interactive CLI demonstration for evaluating RecoveryOS.

---

## 1. Quickstart Execution Commands

To execute the entire test suite and signature demonstration in your terminal:

```bash
# Step 1: Run the full automated test suite (89 passing tests)
python -m pytest -v

# Step 2: Run the 5 signature demo cases CLI showcase
python scripts/demo.py
```

---

## 2. Walkthrough of the 5 Signature Demo Cases

### Case 1: Correct Abstention (Avoiding Value-Destructive Actions)
- **Context**: A micro-transaction of ₹1.00 (`100` paise) fails due to `EXPIRED_PAYMENT_METHOD`.
- **What the Judge Sees**:
  ```text
  [RESULT] Stop Reason : POLICY_ABSTAINED
  [RESULT] Final State : failed
  [RESULT] Total Cost  : INR 0.00
  [AUDIT]  Rationale   : Abstaining: Expected incremental recovery value does not justify intervention cost or risk.
  ```
- **Why It Matters**: Naive agents unconditionally spam payment links costing ₹1.00 in messaging fees + customer friction, resulting in negative net revenue. RecoveryOS evaluates the economic equation and actively chooses `NO_ACTION`.
- **What to Say**: *"Notice that RecoveryOS evaluates the expected net value before acting. Because the intervention cost equals or exceeds the amount at risk, the agent intentionally abstains, preserving both margin and customer goodwill."*

---

### Case 2: Delayed Retry Economic Selection (Candidate Comparison)
- **Context**: A ₹5,000.00 transaction fails with a `TRANSIENT_GATEWAY` error.
- **What the Judge Sees**:
  ```text
  Candidate Action   | Est Prob   | Action Cost  | Exp Net Value  | Selected?
  ----------------------------------------------------------------------
  retry_later        | 80.0%      | INR 0.20     | INR 2749.80    | YES (Optimal)
  retry_now          | 75.0%      | INR 0.20     | INR 2499.80    | no
  payment_link       | 55.0%      | INR 1.00     | INR 1499.00    | no
  reminder           | 45.0%      | INR 0.50     | INR 999.50     | no
  no_action          | 25.0%      | INR 0.00     | INR 0.00       | no
  ----------------------------------------------------------------------
  ```
- **Why It Matters**: Instead of spamming an immediate retry (which often hits the same lingering gateway downtime) or sending an invasive link, RecoveryOS compares all candidates and selects the optimal timed retry (`RETRY_LATER`), generating ₹2,749.80 in expected net value.
- **What to Say**: *"Here we inspect the internal decision matrix. RecoveryOS ranks all admissible candidates by expected net value uplift. Notice that a timed backoff retry achieves higher expected net value than an immediate retry or an expensive payment link."*

---

### Case 3: Late State Change & Stale Action Protection
- **Context**: A payment fails initially, triggering a recovery sequence. While the retry is scheduled, the customer organically logs into their account and pays out-of-band (`payment.captured` event arrives).
- **What the Judge Sees**:
  ```text
  [RESULT] Stop Reason     : TERMINAL_STATE_REACHED
  [RESULT] Final State     : captured
  [RESULT] Captured Amount : INR 2500.00
  [RESULT] Action Cost     : INR 0.00 (Zero wasteful fees)
  ```
- **Why It Matters**: Traditional schedulers blind to asynchronous state changes would have executed the scheduled retry, resulting in a duplicate charge, customer dispute, or merchant chargeback fee. RecoveryOS checks aggregate state immediately prior to dispatch and halts.
- **What to Say**: *"This demonstrates our stale-action guard. Because the aggregate state transitioned to CAPTURED out-of-band, the agent re-evaluates the aggregate before calling the payment gateway and aborts execution with zero duplicate charge risk."*

---

### Case 4: Safety Governor & Consent Enforcement
- **Context**: A rogue or misconfigured policy proposes sending a WhatsApp dunning reminder to a customer who has globally opted out of dunning communications.
- **What the Judge Sees**:
  ```text
  [RESULT] Stop Reason : ACTION_BLOCKED
  [RESULT] Total Cost  : INR 0.00
  [FIREWALL] Error Msg : Customer 'cust_demo_04' has globally opted out of all dunning communications. Action 'reminder' is blocked.
  ```
- **Why It Matters**: AI agents must never bypass merchant compliance and privacy regulations. The `ToolFirewall` intercepts the action proposal, validates consent invariants, and fails closed.
- **What to Say**: *"Here an aggressive policy attempted to send an unsolicited reminder. The ToolFirewall intercepts the proposal, verifies the customer's opt-out preference, and blocks the action unconditionally, failing closed without side effects."*

---

### Case 5: Batch Benchmark Comparison (100 Scenarios)
- **Context**: 100 deterministic scenarios evaluated across 4 baseline policies and RecoveryOS under a ₹2,500 customer churn penalty proxy.
- **What the Judge Sees**:
  ```text
  -------------------------------------------------------------------------------------------------------------------
  Policy                       | Gross Recov | Cost       | Churn Pen  | Adj Net      | Incr Adj Net | Acts  | Avoid | Churn
  -------------------------------------------------------------------------------------------------------------------
  baseline_0_no_action         | INR 21,040  | INR 0.00   | INR 0      | INR 21,040   | INR 0        | 0     | 100   | 0    
  baseline_1_always_retry      | INR 48,846  | INR 20.00  | INR 10,000 | INR 38,826   | INR 17,786   | 100   | 0     | 4    
  baseline_2_static_rules      | INR 122,709 | INR 74.40  | INR 27,500 | INR 95,135   | INR 74,095   | 100   | 0     | 11   
  baseline_3_probability_only  | INR 122,709 | INR 74.40  | INR 27,500 | INR 95,135   | INR 74,095   | 100   | 0     | 11   
  RECOVERYOS_DETERMINISTIC_V0  | INR 121,935 | INR 36.00  | INR 20,000 | INR 101,899  | INR 80,859   | 96    | 4     | 8    
  -------------------------------------------------------------------------------------------------------------------
  ```
- **Why It Matters**: Proves that across a full population, RecoveryOS achieves the highest Incremental Adjusted Net Recovery (₹80,859 vs ₹74,095), reduces customer churn by 27%, cuts action costs by 52%, and avoids 4 value-destructive interventions.
- **What to Say**: *"Finally, this batch benchmark demonstrates our North Star metric across 100 scenarios. RecoveryOS outperforms legacy static rules by over ₹6,700 in incremental net recovery because it protects customer lifetime value, avoids useless actions, and selects economically optimal interventions."*
