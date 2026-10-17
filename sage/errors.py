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

class TruncatedResponse(InvalidResponse):
    code = "truncated_response"

class RetrievalUnavailable(TransientProviderError):
    code = "retrieval_unavailable"

class RateLimited(TransientProviderError):
    code = "rate_limited"

    def __init__(self, message, retry_after_seconds=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds

# Only these authored strings may enter diagnostics or retry instructions.
# Never reflect unknown JSON keys, model values, or arbitrary exception messages.
_VALIDATION_RULES = {
    'json_object': 'Return one valid JSON object without markdown fences.',
    'duplicate_key': 'Do not repeat JSON object keys.',
    'schema_keys': 'Return exactly the requested schema keys, no missing or extra fields.',
    'nonempty_text': 'This field must contain nonempty text; use explicit uncertainty when appropriate.',
    'unique_ids': 'This field must be a JSON array of unique, nonempty string IDs.',
    'integer_index': 'Return an integer index.',
    'list_required': 'Return a JSON list for this field.',
    'source_ownership': 'Use only the authorized source IDs for this role and accepted critiques; visibility is not permission.',
    'critique_status': 'Critique status must be exactly supported or unknown.',
    'revision_decisions': 'Decide every incoming critique exactly once; never accept unknown or failed critiques.',
    'unchanged_idea': 'With no accepted new critique, copy candidate.idea exactly, without paraphrasing or formatting changes.',
    'changed_idea': 'Accepting a critique requires a changed idea.',
    'verbatim_requirement': 'Include every accepted requested_change verbatim, including prior accepted changes.',
    'retained_evidence': 'Retain all source IDs cited by accepted critiques.',
    'selection_range': 'Select an index within the supplied candidate list.',
    'accepted_critique_set': 'Preserve exactly the selected student accepted critique IDs.',
    'requirement_shape': 'Each planning requirement must be an object with the specified fields.',
    'canonical_requirement': 'Copy the matching accepted requested_change verbatim into its planning requirement.',
    'requirements_coverage': 'Include exactly one planning requirement per accepted critique.',
    'required_tag': 'Return exactly one nonempty required output tag.',
    'unspecified': 'Output failed validation; follow the original contract without inventing a diagnosis.',
}
_VALIDATION_FIELDS = frozenset(('$', 'discussion', 'experiment', 'plan_contract', 'idea',
    'status', 'evidence_ids', 'accepted_critique_ids', 'rejected_critique_ids', 'selected_index',
    'requirements', 'critique_id', 'requirement', 'rationale', 'uncertainty', 'issue',
    'requested_change', 'support'))


class ValidationError(InvalidResponse):
    """Safe field/rule diagnostics; retains InvalidResponse compatibility."""
    def __init__(self, rule='unspecified', field='$'):
        self.rule = rule if rule in _VALIDATION_RULES else 'unspecified'
        self.field = field if field in _VALIDATION_FIELDS else '$'
        super().__init__(_VALIDATION_RULES[self.rule])

    def diagnostic(self):
        return {'rule': self.rule, 'field': self.field, 'instruction': _VALIDATION_RULES[self.rule]}
