"""Public, sanitized failure categories for SAGE clients and audit logs."""
class SageError(Exception):
    code = "sage_error"

class ConfigurationError(SageError):
    code = "configuration_error"

class ProviderError(SageError):
    code = "provider_error"

class TransientProviderError(ProviderError):
    code = "transient_provider_error"

class InvalidResponse(SageError):
    code = "invalid_response"

class BudgetExceeded(SageError):
    code = "budget_exceeded"

class NoEvidence(SageError):
    code = "no_evidence"
