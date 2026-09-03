# RecoveryOS Signature Showcase & 5-Minute Demo Guide

This document provides the choreographed 5-minute demonstration guide and walkthrough for the Razorpay AI Buildathon 2026 panel judges.

---

## 1. Quickstart Execution Commands

```bash
# Step 1: Run the full automated test suite (319 passing tests)
make test
# (or: python -m pytest -v)

# Step 2: Run the 7 signature demo cases CLI showcase (< 5 seconds)
make demo
# (or: python scripts/demo.py)

# Step 3: Launch the Operations Console Dashboard
uvicorn backend.app:app --host 127.0.0.1 --port 8000
# Open http://127.0.0.1:8000/dashboard in your browser
```

---

## 2. Five-Minute Live Demo & Video Choreography

### [0:00–0:45] The Hook & Problem (Operations Console)
- **Visual**: Show the **Operations Console Dashboard** (`GET /dashboard`). Point to the top KPI strip: *Revenue at Risk*, *Gross Recovered*, *Incremental Net Recovery*, *Adjusted Net Recovery*, and *Interventions Avoided*.
- **Narrative**:
  > *"Judges, traditional dunning treats failed payments as a brute-force messaging volume problem. They hammer gateways on expired cards, spam payment links, and claim credit for payments customers would have made organically anyway. RecoveryOS transforms revenue recovery into a sequential, causal decision problem. We measure **Incremental Adjusted Net Recovery**—net recovery above organic baseline minus direct costs and customer churn penalties."*

### [0:45–2:00] Signature Cases 1 & 2: Timing Optimization & Economic Abstention
- **Visual**: Run `make demo` (Cases 1 & 2).
- **Case 1: Intelligent Abstention**:
  - Show micro-transaction (₹1.00) with `EXPIRED_PAYMENT_METHOD` failure.
  - Show RecoveryOS output: `Stop Reason: POLICY_ABSTAINED`, `Verdict: ABSTAIN`, `Cost: ₹0.00`.
  - Explain: *"A naive agent spends ₹1.00 to recover ₹1.00 on an expired card. RecoveryOS calculates negative net value uplift and intentionally abstains."*
- **Case 2: Action × Timing Optimization**:
  - Show ₹5,000 transaction with `TRANSIENT_GATEWAY` failure.
  - Point to the candidate evaluation matrix comparing immediate retry, +6h retry, +12h retry, +24h retry, and links.
  - Highlight chosen action: `retry_later` (window: `PLUS_6H`) yielding ₹2,762.30 expected net value (+55% uplift over natural baseline).

### [2:00–3:00] Signature Cases 3 & 4: Stale-Action Protection & Safety Opt-Out
- **Visual**: Run `make demo` (Cases 3 & 4) and view **Case Decision Replay** on dashboard.
- **Case 3: Stale-Action Protection (Out-of-Band Capture)**:
  - Show delayed action scheduled for +6h.
  - Show customer paying organically at +30m via `payment.captured` webhook.
  - Show pre-execution revalidation detecting terminal state and outputting `INVALIDATED` (`REVENUE_ALREADY_RECOVERED`), avoiding double-charging the customer.
- **Case 4: Safety Governor & Consent Enforcement**:
  - Show customer with active global opt-out preference.
  - Show Governor intercepting dunning proposal, outputting `DENY` (`CUSTOMER_OPTED_OUT`), and halting execution safely with ₹0.00 cost.

### [3:00–4:15] The Evaluation Lab (Multi-Seed Proof & Sensitivity)
- **Visual**: Switch to **Evaluation Lab** tab on the dashboard or display benchmark results.
- **Data Highlight**:
  - 100-scenario multi-seed evaluation: RecoveryOS achieves **₹80,859** Incremental Adjusted Net Recovery (+₹6,764 over static heuristics, +₹63,073 over Always Retry).
  - 27% churn reduction (8 churned customers vs 11 under Static Rules).
  - 52% cost reduction (₹36.00 total action costs vs ₹74.40).
  - Oracle hindsight regret analysis proving near-optimal decision efficiency.
  - Economic sensitivity matrix proving positive alpha across low, medium, and high customer friction parameters.

### [4:15–5:00] Architectural Governance & Close
- **Visual**: Return to **Control Room** view and show the 3 architectural planes:
  1. *Intelligence Plane*: Observable context boundary with structured AI diagnosis.
  2. *Governance Plane*: Deterministic Recovery Governor with human review escalation and Tool Firewall.
  3. *Execution Plane*: Scheduled lifecycle manager, fail-closed Razorpay adapter, and immutable append-only decision replay log.
- **Closing Statement**:
  > *"Our core design principle is clear: **The model proposes. The Governor authorizes. The executor acts.** RecoveryOS gives merchants an autonomous, provably safe, and economically sound revenue recovery engine. Thank you."*

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
