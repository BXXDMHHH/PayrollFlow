"""Application-level exceptions with safe, user-readable messages."""


class PayrollFlowError(Exception):
    """Base exception for expected PayrollFlow failures."""


class ConfigurationError(PayrollFlowError):
    """Raised when an application configuration is missing or invalid."""
