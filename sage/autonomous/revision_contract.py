"""Evidence-led synthesis revisions with exact, manager-computed change coverage.

This validates an author's responsibility record, not its scientific truth.
Scores, rankings and schema convenience are not admissible revision bases; a
scientific metric named score can still be discussed in the actual protocol.
"""
from __future__ import annotations

import json
import re

from .review import CANDIDATE_SCIENTIFIC_FIELDS, CONTEXT_SCIENTIFIC_FIELDS, scientific_context


VERSION = 'sage.autonomous.revision-contract.v1'
BASES = ('supported_issue', 'contradicting_evidence', 'protocol_correction', 'feasibility')
_RECORD_FIELDS = frozenset({
    'schema_version', 'parent_sha256', 'change_type', 'basis', 'problem_assessment',
    'remedy_assessment', 'reason', 'remaining_uncertainty', 'candidate_changes',
    'withdrawn_selected',
})


def revision_descriptor():
    return {
        'schema_version': VERSION,
        'candidate_scientific_fields': sorted(CANDIDATE_SCIENTIFIC_FIELDS),
        'context_scientific_fields': sorted(CONTEXT_SCIENTIFIC_FIELDS),
        'selection_change_field': 'selected',
        'template': {
            'schema_version': VERSION, 'parent_sha256': 'exact manager-provided previous primary SHA-256',
            'change_type': 'scientific_revision|no_scientific_change',
            'basis': ['supported_issue|contradicting_evidence|protocol_correction|feasibility'],
            'problem_assessment': 'Identify the scientific problem; metadata-only may state not applicable.',
            'remedy_assessment': 'Explain why this remedy is preferable or reject the advice with reasons.',
            'reason': 'Scientific grounds, rather than a sampled model score or schema convenience.',
            'remaining_uncertainty': 'Explicit remaining uncertainty; do not claim the record proves improvement.',
            'candidate_changes': [{
                'candidate_id': 'an actually changed candidate ID',
                'changed_fields': ['exact changed scientific fields and/or selected'],
                'scientific_reason': 'Why these changes address the actual problem.',
                'source_ids': ['actual retrieved source IDs, or empty for protocol reasoning'],
            }],
            'context_changes': [{
                'field': 'an actually changed top-level scientific context field',
                'scientific_reason': 'Why the shared scientific context needs this change.',
                'source_ids': ['actual retrieved source IDs, or empty for protocol reasoning'],
            }],
            'withdrawn_selected': [{
                'candidate_id': 'previously selected ID no longer selected',
                'scientific_reason': 'Specific scientific grounds for withdrawal; preserve its ledger entry.',
                'source_ids': ['actual retrieved IDs; may be empty only with the constraint below'],
                'constraint': {'kind': 'protocol|feasibility',
                               'description': 'Concrete invalid identification/protocol or resource constraint'},
            }],
        },
        'instructions': [
            'Required for each changed synthesis after the first; parent_sha256 must name its immediate predecessor.',
            'Keep every previous candidate in the ledger, even if rejected or no longer selected.',
            'candidate_changes must cover exactly every actual candidate science/selection change and exactly its fields.',
            'context_changes must cover exactly every changed top-level scientific context field; use [] or omit only when none changed.',
            'Shared protocols, metrics, resources and projected open objections are scientific context, not metadata.',
            'A newly added candidate lists every scientific field it introduces and selected if newly selected.',
            'Source order, titles, provenance and author metadata alone are not scientific changes.',
            'For metadata-only changes use no_scientific_change, basis=[], candidate_changes=[], context_changes=[] and withdrawn_selected=[].',
            'A scientific revision needs one or more allowed bases; score/rank/acceptance/schema convenience are not bases.',
            'Every withdrawn selected ID needs specific scientific grounds and actual sources or a concrete protocol/feasibility constraint.',
            'The constraint field is optional if source_ids is nonempty; omit it rather than inventing a constraint.',
            'Do not manufacture a flaw, accept reviewer advice automatically, or treat this record as independent validation.',
        ],
        'validation_scope': 'Exact structural accountability; problem/remedy correctness and semantic support remain unverified.',
    }


def _candidates(document, label, errors):
    if not isinstance(document, dict) or not isinstance(document.get('candidates'), list):
        errors.append(label + ' must contain a candidates list')
        return {}, set()
    candidates = {}
    for candidate in document['candidates']:
        if (not isinstance(candidate, dict) or not isinstance(candidate.get('id'), str)
                or not candidate['id'].strip()):
            errors.append(label + ' candidate IDs must be nonempty strings')
            continue
        ident = candidate['id']
        if ident in candidates:
            errors.append(label + ' candidate IDs must be unique')
        candidates[ident] = candidate
    selected = document.get('selected_ids')
    if (not isinstance(selected, list) or any(not isinstance(x, str) or x not in candidates for x in selected)
            or len(selected) != len(set(selected))):
        errors.append(label + ' selected_ids must contain unique known candidate IDs')
        selected = []
    return candidates, set(selected)


def _scientific_value(field, value):
    # Same source-set semantics as TeamBoard's substantive-change detection.
    if field == 'source_ids' and isinstance(value, list) and all(isinstance(x, str) for x in value):
        value = sorted(set(value))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _expected_changes(previous, selected_before, current, selected_after):
    changed = {}
    missing = object()
    for ident in set(previous) | set(current):
        before, after = previous.get(ident, {}), current.get(ident, {})
        fields = []
        for field in sorted(CANDIDATE_SCIENTIFIC_FIELDS):
            old, new = before.get(field, missing), after.get(field, missing)
            if old is missing and new is missing:
                continue
            if old is missing or new is missing or _scientific_value(field, old) != _scientific_value(field, new):
                fields.append(field)
        if (ident in selected_before) != (ident in selected_after):
            fields.append('selected')
        if fields:
            changed[ident] = fields
    return changed


def revision_errors(previous_document, previous_sha, document, *, known_sources):
    """Return accountability errors without altering documents or judging science.

    The caller supplies a manager-frozen predecessor SHA and retrieved source
    set. Hash identity cannot be reconstructed from a parsed dict's formatting.
    """
    errors = []
    previous, selected_before = _candidates(previous_document, 'Previous primary', errors)
    current, selected_after = _candidates(document, 'Current primary', errors)
    if not isinstance(previous_sha, str) or not re.fullmatch('[0-9a-f]{64}', previous_sha):
        errors.append('Revision requires an exact manager-frozen previous SHA-256')
    removed = set(previous) - set(current)
    if removed:
        errors.append('Preserve every old candidate in the ledger; missing IDs: ' + ', '.join(sorted(removed)))
    if not isinstance(known_sources, (set, frozenset, list, tuple, dict)) or any(
            not isinstance(x, str) for x in known_sources):
        errors.append('known_sources must contain manager-retrieved source IDs')
        known_sources = set()
    else:
        known_sources = set(known_sources)
    try:
        changes = _expected_changes(previous, selected_before, current, selected_after)
        old_context = scientific_context(previous_document, previous)
        new_context = scientific_context(document, current)
        context_changes = {field for field in set(old_context) | set(new_context)
                           if field not in old_context or field not in new_context
                           or _scientific_value(field, old_context[field]) != _scientific_value(field, new_context[field])}
    except (ValueError, TypeError):
        errors.append('Scientific revision fields must be finite JSON data')
        changes = {}
        context_changes = set()
    record = document.get('revision_record') if isinstance(document, dict) else None
    if not isinstance(record, dict):
        return errors + ['Changed synthesis requires revision_record; request protocol_schema for its contract']
    if not _RECORD_FIELDS <= set(record) or set(record) - _RECORD_FIELDS - {'context_changes'}:
        errors.append('revision_record must contain the declared contract fields and optional context_changes')
    if record.get('schema_version') != VERSION:
        errors.append('Unknown revision_record schema version')
    if record.get('parent_sha256') != previous_sha:
        errors.append('revision_record parent_sha256 must match the immediate manager-frozen predecessor')
    for field in ('problem_assessment', 'remedy_assessment', 'reason', 'remaining_uncertainty'):
        if not isinstance(record.get(field), str) or not record[field].strip():
            errors.append('revision_record ' + field + ' must be nonempty text')
    basis = record.get('basis')
    if (not isinstance(basis, list) or any(not isinstance(x, str) or x not in BASES for x in basis)
            or len(basis) != len(set(basis))):
        errors.append('Revision basis must use unique allowed scientific grounds; score/rank/schema convenience are not grounds')
    scientific_change = bool(changes or context_changes)
    expected_type = 'scientific_revision' if scientific_change else 'no_scientific_change'
    if record.get('change_type') != expected_type:
        errors.append('revision_record change_type must be ' + expected_type + ' for the actual fields')
    if scientific_change and not basis:
        errors.append('A scientific revision requires at least one explicit scientific basis')
    if not scientific_change and basis:
        errors.append('A metadata-only revision must use basis=[] without inventing scientific problems')

    def source_ids(item, label):
        ids = item.get('source_ids')
        if (not isinstance(ids, list) or any(not isinstance(x, str) or x not in known_sources for x in ids)
                or len(ids) != len(set(ids))):
            errors.append(label + ' source_ids must be unique actually retrieved IDs')
            return []
        return ids

    def rows(field):
        values = record.get(field)
        if not isinstance(values, list):
            errors.append('revision_record ' + field + ' must be a list')
            return {}
        result = {}
        for item in values:
            if (not isinstance(item, dict) or not isinstance(item.get('candidate_id'), str)
                    or not item['candidate_id'].strip()):
                errors.append(field + ' entries must name a candidate_id')
                continue
            ident = item['candidate_id']
            if ident in result:
                errors.append(field + ' cannot repeat a candidate_id')
            result[ident] = item
            if not isinstance(item.get('scientific_reason'), str) or not item['scientific_reason'].strip():
                errors.append(field + ' ' + ident + ' needs a specific scientific_reason')
        return result

    declared = rows('candidate_changes')
    if set(declared) != set(changes):
        errors.append('candidate_changes must exactly cover actual candidate scientific/selection changes')
    for ident, item in declared.items():
        if set(item) != {'candidate_id', 'changed_fields', 'scientific_reason', 'source_ids'}:
            errors.append('candidate_changes entries must contain exactly the declared contract fields')
        fields = item.get('changed_fields')
        if (not isinstance(fields, list) or any(not isinstance(x, str) for x in fields)
                or len(fields) != len(set(fields)) or set(fields) != set(changes.get(ident, []))):
            errors.append('candidate_changes ' + ident + ' changed_fields must exactly match actual fields')
        source_ids(item, 'candidate_changes ' + ident)
    context_rows = record.get('context_changes', [])
    declared_context = set()
    if not isinstance(context_rows, list):
        errors.append('context_changes must be a list')
    else:
        for item in context_rows:
            if (not isinstance(item, dict) or set(item) != {'field', 'scientific_reason', 'source_ids'}
                    or not isinstance(item.get('field'), str) or item['field'] not in CONTEXT_SCIENTIFIC_FIELDS):
                errors.append('context_changes entries must name a declared scientific context field, reason and source_ids')
                continue
            field = item['field']
            if field in declared_context:
                errors.append('context_changes cannot repeat a field')
            declared_context.add(field)
            if not isinstance(item['scientific_reason'], str) or not item['scientific_reason'].strip():
                errors.append('context_changes ' + field + ' needs a specific scientific_reason')
            source_ids(item, 'context_changes ' + field)
    if declared_context != context_changes:
        errors.append('context_changes must exactly cover actual top-level scientific changes')
    withdrawals = rows('withdrawn_selected')
    if set(withdrawals) != selected_before - selected_after:
        errors.append('withdrawn_selected must exactly cover every previously selected ID no longer selected')
    for ident, item in withdrawals.items():
        if set(item) - {'candidate_id', 'scientific_reason', 'source_ids', 'constraint'}:
            errors.append('withdrawn_selected entries have unknown contract fields')
        ids = source_ids(item, 'withdrawn_selected ' + ident)
        constraint = item.get('constraint')
        valid_constraint = (isinstance(constraint, dict) and set(constraint) == {'kind', 'description'}
                            and constraint.get('kind') in ('protocol', 'feasibility')
                            and isinstance(constraint.get('description'), str) and bool(constraint['description'].strip()))
        if constraint is not None and not valid_constraint:
            errors.append('Withdrawal constraint must identify a concrete protocol/feasibility limitation')
        if not ids and not valid_constraint:
            errors.append('Withdrawal ' + ident + ' requires actual sources or a concrete protocol/feasibility constraint')
    return errors
