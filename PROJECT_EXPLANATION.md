# RecoveryOS: Autonomous AI Revenue Recovery Agent

RecoveryOS is an enterprise-grade autonomous revenue recovery and dunning intelligence agent developed for the **Razorpay AI Buildathon 2026 (Track 03)**. The platform ingests asynchronous payment and subscription webhooks securely from Razorpay, reconstructs real-time financial states, and executes governed, bounded recovery decisions.

---

## 1. System Architecture (Phase 1)

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
                     |  - WebhookPayload & Entities      |
                     +-----------------+-----------------+
                                       |
                                       v
    +-----------------------------------------------------------------------+
    |                         Domain Layer (domain/)                        |
    |  - Enums (RevenueState, PaymentState, SubscriptionState, ActionType)  |
    |  - Events (PaymentEntity, SubscriptionEntity, PaymentEvent)           |
    |  - Governance (Action, ActionParams, Decision, GuardrailCheckResult)  |
    +-----------------------------------------------------------------------+
                                       |
                                       v
    +-----------------------------------------------------------------------+
    |                       Execution Layer (execution/)                    |
    |  - RazorpayAdapter (Abstract Boundary Interface)                      |
    |  - MockAdapter (In-memory Simulation & State Tracking)                |
    +-----------------------------------------------------------------------+
```

---

## 2. Core Modules & Contracts

### 2.1 Domain Layer (`domain/`)
- **`domain/enums.py`**:
  - `RevenueState`: Account lifecycle stages (`healthy`, `at_risk`, `critical`, `lost`, `recovered`).
  - `PaymentState`: Razorpay payment statuses (`created`, `authorized`, `captured`, `refunded`, `failed`).
  - `SubscriptionState`: Subscription states (`created`, `authenticated`, `active`, `pending`, `halted`, `cancelled`, `completed`, `expired`).
  - `ActionType` & `DecisionType`: Machine-actionable recovery intents.
- **`domain/events.py`**:
  - `PaymentEntity` & `SubscriptionEntity`: Exact mirror of Razorpay JSON payloads with strict typing.
  - `WebhookPayload`: Root webhook envelope containing account metadata and entity containers.
  - `PaymentEvent`: Normalized internal event model.
- **`domain/actions.py`**:
  - `Action` & `ActionParams`: Strongly-typed execution instructions with parameter bounds.
  - `Decision`: Governed decision containing audit rationale, confidence score, and guardrail compliance records.

### 2.2 Ingestion & Security Layer (`backend/`)
- **`backend/dependencies/security.py`**:
  - Webhooks are cryptographically validated using HMAC SHA-256 against `RAZORPAY_WEBHOOK_SECRET`.
  - Raw body bytes are consumed directly via `Request.body()` before parsing to prevent whitespace or key-reordering discrepancies.
  - Constant-time verification using `hmac.compare_digest` prevents timing side-channel attacks.
- **`backend/api/webhooks.py`**:
  - Processes authenticated payloads and enforces schema validation.

### 2.3 Execution Layer (`execution/`)
- **`execution/base.py`**:
  - Defines the `RazorpayAdapter` abstract contract.
- **`execution/mock_adapter.py`**:
  - Offline, high-fidelity mock implementation for deterministic unit and integration testing without network calls or third-party dependencies.

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
