# Changelog

All notable changes to the RecoveryOS platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-31
### Added
- **Synthetic Revenue-Recovery Environment (Simulator v1)**:
  - Configuration models (`SimulatorConfig`, `ScenarioConfig`, `FailureClass`, `CustomerArchetype`, `SimulatedActionType`) (`simulator/config.py`).
  - Behavioral archetype matrices and failure physics models (`ARCHETYPE_PROFILES`, `FAILURE_CLASS_BEHAVIORS`) (`simulator/archetypes.py`).
  - Hidden Potential Outcome Model $Y(a)$ computing counterfactual recovery, delay, churn, fatigue, and cost across all actions (`simulator/outcomes.py`).
  - Synthetic entity generator emitting strictly typed `SimulatedCustomer`, `PaymentEntity`, `WebhookPayload`, and `PaymentEvent` models (`simulator/entities.py`).
  - Batch scenario generator orchestrator with isolated PRNG seed management for 100% deterministic reproducibility (`simulator/generator.py`).
- **Test Suite**:
  - 45 total tests including bit-level reproducibility assertions, statistical distribution verification between archetypes (`NATURAL_RECOVERER` vs `NON_RESPONSIVE`), counterfactual outcome completeness, expired payment method hard-failure constraints, and seamless integration with the Phase 2 `IngestionService` (`tests/unit/test_simulator.py`).

## [0.2.0] - 2026-08-31
### Added
- **Domain Aggregates**:
  - `PaymentAggregate` and `SubscriptionAggregate` tracking financial state, version counter, and chronologically sorted event timeline (`domain/aggregates.py`).
- **Event Store & Idempotency Abstractions**:
  - `EventStore` interface and `InMemoryEventStore` with chronological event query by `occurred_at` (`ingestion/store.py`).
  - `IdempotencyTracker` interface and `InMemoryIdempotencyTracker` caching execution results and preventing duplicate side-effects (`ingestion/idempotency.py`).
- **State Reconciliation Engine**:
  - `StateReconciler` resolving out-of-order, duplicate, and late event arrivals deterministically (`ingestion/reconciler.py`).
  - Terminal state protection: Preserves `CAPTURED` terminal state when delayed failure webhooks arrive.
  - Strict transition matrix enforcing valid state transitions and raising `InvalidStateTransitionError` on illegal forward mutations.
- **Ingestion Orchestration Service**:
  - `IngestionService` coordinating cryptographic verification, idempotency checking, event appending, and aggregate state reconstruction (`backend/services/ingestion_service.py`).
  - Updated `POST /webhooks/razorpay` to return structured idempotency and state metadata (`backend/api/webhooks.py`).
- **Test Suite**:
  - 39 unit and integration tests including adversarial fintech scenarios: duplicate webhooks, out-of-order `captured` vs `authorized`, late failure absorption, and invalid transition rejection (`tests/unit/test_idempotency.py`, `tests/integration/test_reconciliation.py`).

## [0.1.0] - 2026-08-31
### Added
- **Repository Setup**: Initialized repository structure with `.gitignore`, `pyproject.toml`, and `requirements.txt`.
- **Domain Layer Contracts**:
  - `RevenueState`, `PaymentState`, `SubscriptionState`, `ActionType`, `DecisionType`, and `ActionStatus` enums (`domain/enums.py`).
  - Strict Pydantic v2 event and webhook models (`PaymentEntity`, `SubscriptionEntity`, `WebhookPayload`, `PaymentEvent`) (`domain/events.py`).
  - Strict Pydantic v2 action and decision contracts (`Action`, `ActionParams`, `Decision`, `GuardrailCheckResult`) (`domain/actions.py`).
- **Execution Adapter Boundary**:
  - `RazorpayAdapter` abstract base class defining payment/subscription operations and governed action execution (`execution/base.py`).
  - `MockAdapter` providing in-memory simulation with state tracking without network calls (`execution/mock_adapter.py`).
- **FastAPI Webhook Ingestion & Security**:
  - Secure HMAC SHA-256 webhook signature verification dependency using raw `Request.body()` and constant-time comparison `hmac.compare_digest` (`backend/dependencies/security.py`).
  - Webhook route `POST /webhooks/razorpay` validating signatures and parsing payloads into domain models (`backend/api/webhooks.py`).
  - FastAPI application entrypoint with health check endpoint (`backend/app.py`).
- **Test Suite**:
  - 31 unit and integration tests covering domain validation, MockAdapter state mutation, HMAC signature validation, tamper prevention, missing header rejection, and error handling (`tests/unit/test_domain.py`, `tests/integration/test_webhook_security.py`).
