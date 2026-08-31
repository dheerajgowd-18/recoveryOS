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
```

---

## 2. Core Modules & Contracts

### 2.1 Ingestion & Idempotency Layer (`ingestion/`)
- **`ingestion/idempotency.py`**:
  - `IdempotencyTracker` & `InMemoryIdempotencyTracker`: Tracks processed `event_id` keys and caches execution acknowledgments.
  - Replays of identical webhook deliveries return cached results with `is_duplicate = True` without re-evaluating business state.
- **`ingestion/store.py`**:
  - `EventStore` & `InMemoryEventStore`: Append-only event stream providing timeline sorting by `occurred_at` (business time).
  - Snapshot persistence for `PaymentAggregate` and `SubscriptionAggregate`.
- **`ingestion/reconciler.py`**:
  - `StateReconciler`: Implements deterministic state transition matrices.
  - **Out-of-order handling**: Reconstructs state based on `occurred_at` rather than delivery arrival order (`received_at`).
  - **Terminal State Protection**: Once a transaction achieves terminal state (`CAPTURED` or `REFUNDED`), delayed arrival of older `payment.failed` webhooks will not corrupt the terminal state. Late events are safely absorbed into the audit timeline.
  - **Illegal Transition Detection**: Forward attempts to transition from terminal states (e.g. `CAPTURED` -> `FAILED`) trigger explicit `InvalidStateTransitionError` exceptions.

### 2.2 Domain Layer (`domain/`)
- **`domain/aggregates.py`**:
  - `PaymentAggregate` & `SubscriptionAggregate`: Encapsulate current state, monotonic versioning, full event history, error logs, and late event counters.
- **`domain/enums.py`**:
  - `RevenueState`, `PaymentState`, `SubscriptionState`, `ActionType`, `DecisionType`, `ActionStatus`.
- **`domain/events.py`**:
  - Strongly typed Pydantic v2 schemas: `PaymentEntity`, `SubscriptionEntity`, `WebhookPayload`, `PaymentEvent`.
- **`domain/actions.py`**:
  - `Action`, `ActionParams`, `Decision`, `GuardrailCheckResult`.

### 2.3 Execution Layer (`execution/`)
- **`execution/base.py` & `execution/mock_adapter.py`**:
  - `RazorpayAdapter` interface and high-fidelity `MockAdapter` for offline simulation of actions and gateway queries.

---

## 3. Running & Verifying

### 3.1 Installation
```bash
pip install -r requirements.txt
```

### 3.2 Running the Application
```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

### 3.3 Running Test Suite
```bash
pytest -v
```
