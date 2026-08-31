"""Custom exception hierarchy for safety governor, tool firewall, and runtime fault handling."""


class FirewallError(Exception):
    """Base exception for all tool firewall and safety governor errors."""
    pass


class ActionBlockedError(FirewallError):
    """Raised when an intervention action violates governance guardrails or constraints."""
    pass


class SchemaValidationError(FirewallError):
    """Raised when a candidate action dictionary or model fails strict schema validation."""
    pass


class ConsentViolationError(ActionBlockedError):
    """Raised when an action violates customer communication consent or opt-out settings."""
    pass


class DuplicateExecutionError(ActionBlockedError):
    """Raised when an action dispatch attempts to reuse an existing idempotency execution key."""
    pass


class PolicyOutageError(FirewallError):
    """Raised when the policy decision service experiences an outage or becomes unavailable."""
    pass
