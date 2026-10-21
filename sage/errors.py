"""Public, sanitized failure categories for SAGE clients and audit logs."""
class SageError(Exception):
    code = "sage_error"

class ConfigurationError(SageError):
    code = "configuration_error"

class RequestCapacityError(ConfigurationError):
    """Authored local preflight diagnostics; never an external error body."""
    code = "request_capacity_error"
    _messages = {
        'invalid_prompt': 'Prompt must be nonempty UTF-8 text.',
        'invalid_output_budget': 'Requested output exceeds the supported output-token limit.',
        'payload_limit_exceeded': 'Request exceeds the separate local UTF-8 payload bound.',
        'unknown_model_capacity': 'Request exceeds the conservative character bound for an unverified model profile.',
        'tokenizer_asset_missing': 'Official tokenizer asset is missing; run the native environment setup.',
        'tokenizer_asset_invalid': 'Official tokenizer asset failed its pinned integrity check; repair the environment setup.',
        'tokenizer_unavailable': 'Official tokenizer runtime is unavailable; repair the environment setup.',
        'context_capacity_exceeded': 'Input tokens, requested output and chat allowance exceed the documented context.',
    }

    def __init__(self, reason, capacity=None):
        self.reason = reason if reason in self._messages else 'invalid_prompt'
        self.capacity = {}
        for key in ('input_characters', 'input_utf8_bytes', 'text_tokens', 'requested_output_tokens',
                    'context_tokens', 'maximum_output_tokens', 'chat_overhead_reserved',
                    'total_reserved_tokens', 'payload_limit_bytes', 'legacy_character_limit'):
            value = (capacity or {}).get(key)
            if value is None or (type(value) is int and value >= 0):
                self.capacity[key] = value
        super().__init__(self._messages[self.reason])

    def diagnostic(self):
        return {'code': self.code, 'reason_code': self.reason,
                'message': self._messages[self.reason], 'network_request': False,
                **self.capacity}

class ProviderError(SageError):
    code = "provider_error"

class TransientProviderError(ProviderError):
    code = "transient_provider_error"

class ValidationDetailError(ValueError):
    """ValueError with a structured, ID-level validation diagnostic.

    The detail dict carries only IDs and reference-number strings (source_ids,
    reference_ids, candidate ids, reasons, allowed ID sub-tables). It never
    contains paper full text: papers remain manager-private and agents can only
    read them through the passages tool. Downstream surfaces must treat
    ``detail`` as untrusted DATA (reference data for the repair), never as
    instructions.
    """
    def __init__(self, message, detail):
        self.detail = detail
        super().__init__(message)

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
    'claim_queries_1': 'Return at most ONE short query in each claims[].queries array. Do not return three aspect queries.',
    'claim_queries_2': 'Return at most TWO short queries in each claims[].queries array. Select two aspects; do not return three.',
    'claim_queries_3': 'Return at most THREE short queries in each claims[].queries array.',
    'json_object': 'Return one valid JSON object without markdown fences.',
    'duplicate_key': 'Do not repeat JSON object keys.',
    'schema_keys': 'Return exactly the requested schema keys, no missing or extra fields.',
    'nonempty_text': 'This field must contain nonempty text; use explicit uncertainty when appropriate.',
    'unique_ids': 'This field must be a JSON array of unique, nonempty string IDs.',
    'integer_index': 'Return an integer index.',
    'list_required': 'Return a JSON list for this field.',
    'source_ownership': 'Use only IDs authorized by citable_source_ids in this task; do not invent IDs.',
    'critique_status': 'Use an allowed critique status: supported/unknown, or methodological when v3 permits it.',
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
    'bounded_commentary': 'Response exceeds the transport envelope. Split the manuscript into subsections without discarding evidence or compressing the argument.',
    'manuscript_prose': 'Return the actual rewritten manuscript paragraph, not editing instructions, a review reply, or advice to the author. Replace directives such as Clarify the abstract or Separate the proposal with the final prose itself.',
    'bounded_ranking_reason': 'Each raw ranking reason must be at most 1200 characters; the controller preserves full text and creates a marked 180-character preview. Preserve all supplied IDs and numeric scores.',
    'source_excerpt': 'Copy a contiguous 15-280 character quote only from INPUT_CHUNK, not from metadata or another chunk. Keep claims <=350 characters and the exact supplied chunk_id; omit unsupported claims.',
    'source_span_id': 'Select only passage IDs present in INPUT_PASSAGES. Do not invent IDs or copy quotations. Return exactly one <capsule> JSON tag with category, claim and span_ids per claim.',
    'canonical_requirements_managed': 'Return requirements=[] in v3. The controller attaches exact approved requirements from selected accepted_critique_ids.',
}
_VALIDATION_FIELDS = frozenset(('$', 'discussion', 'experiment', 'plan_contract', 'idea', 'commentary',
    'status', 'evidence_ids', 'accepted_critique_ids', 'rejected_critique_ids', 'selected_index',
    'requirements', 'critique_id', 'requirement', 'rationale', 'uncertainty', 'issue',
    'requested_change', 'support', 'reason', 'quote', 'queries', 'span_ids', 'capsule', 'entailment'))

# Authored literal wrappers, never an arbitrary tag name from model/source text.
# A rejected entailment response must say WHICH wrapper is missing; silently
# reducing the trusted tag field to "$" made otherwise useful retries ambiguous.
_REQUIRED_TAG_INSTRUCTIONS = {
    'capsule': 'Return exactly one nonempty <capsule>...</capsule> wrapper containing the complete requested JSON object. Close all JSON arrays and objects before </capsule>. Do not return bare JSON, markdown fences, an empty wrapper, duplicate wrappers, or a partial closing tag.',
    'entailment': 'Return exactly one nonempty <entailment>...</entailment> wrapper containing the complete requested JSON object. Close all JSON arrays and objects before </entailment>. Do not return bare JSON, markdown fences, an empty wrapper, duplicate wrappers, or a partial closing tag.',
}


class ValidationError(InvalidResponse):
    """Safe field/rule diagnostics; retains InvalidResponse compatibility."""
    def __init__(self, rule='unspecified', field='$'):
        self.rule = rule if rule in _VALIDATION_RULES else 'unspecified'
        self.field = field if field in _VALIDATION_FIELDS else '$'
        self.instruction = (_REQUIRED_TAG_INSTRUCTIONS.get(self.field, _VALIDATION_RULES[self.rule])
                            if self.rule == 'required_tag' else _VALIDATION_RULES[self.rule])
        super().__init__(self.instruction)

    def diagnostic(self):
        return {'rule': self.rule, 'field': self.field, 'instruction': self.instruction}
