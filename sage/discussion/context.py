"""Lossless evidence interning and task-specific views; full history stays in ledger."""
from copy import deepcopy
from ..checkpoints import digest


def compact_payload(stage, payload):
    result = deepcopy(payload)
    if stage == 'synthesize':
        # Current proposals are already in candidates; nested originals/developments
        # and previous proposal copies add no current state. Preserve decisions,
        # uncertainty, acceptance links and a digest linking to the complete ledger.
        result['students'] = [{
            **{k: s[k] for k in ('student_id', 'role', 'candidate_index', 'evidence_ids', 'accepted_critique_ids')},
            'history_sha256': digest(s),
            'revision_decisions': [{k: v for k, v in revision.items()
                                   if k not in ('idea', 'previous_idea')} for revision in s['revisions']],
            'development_uncertainty': s.get('development', {}).get('uncertainty', '')}
            for s in payload['students']]
    registry = {}

    def intern(value):
        if isinstance(value, list):
            return [intern(x) for x in value]
        if not isinstance(value, dict):
            return value
        if 'paper' in value and isinstance(value['paper'], dict) and 'idea' in value and 'experiment' in value:
            identity = value['paper']['paper_id']
            # Different extractions of one paper must not overwrite each other.
            ref = identity + ':' + digest(value)[:16]
            registry[ref] = value
            return {'paper': {'paper_id': identity}, 'evidence_ref': ref}
        if {'idea', 'chain', 'novelty', 'rejected_attempts'} <= set(value):
            rejected = value['rejected_attempts']
            value = {k: v for k, v in value.items() if k != 'rejected_attempts'}
            # Keep negative evidence/rationale and compared sources. Only previous
            # candidate text is redundant with the retained audit snapshots.
            value['rejected_attempts'] = [{k: v for k, v in attempt.items() if k != 'idea'}
                                          for attempt in rejected]
            value['rejected_history_sha256'] = digest(rejected)
        return {k: intern(v) for k, v in value.items()}

    result = intern(result)
    result['evidence_registry'] = registry
    result['context_policy'] = ('Evidence stubs resolve to full records in evidence_registry. '
        'History is retained in the audit ledger; do not infer unseen history. '
        'Only top-level citable_source_ids authorize citations in your response; '
        'a source appearing in another role or target does not authorize its use.')
    if stage == 'critique':
        result['citable_source_ids'] = list(payload['evidence_ids'])
        result['target_source_ids_not_citable'] = sorted({e['paper']['paper_id']
             for e in payload['target_candidate']['chain']['evidence']} - set(payload['evidence_ids']))
    elif stage == 'revise':
        own = {e['paper']['paper_id'] for e in payload['candidate']['chain']['evidence']}
        prior = {i for c in payload['prior_accepted_critiques'] for i in c['evidence_ids']}
        result['citable_source_ids'] = sorted(own | prior)
        result['evidence_ids'] = sorted(own | prior)
        result['source_ids_conditional_on_acceptance'] = {
            c['critique_id']: c['evidence_ids'] for c in payload['critiques'] if c['status'] == 'supported'}
        result['context_policy'] += (' In revise only, conditional source IDs become authorized '
            'if and only if their supported critique is explicitly accepted; rejecting a critique '
            'does not authorize its sources. Preserve prior accepted sources and changes.')
    elif stage == 'synthesize':
        result['citable_source_ids'] = sorted({identifier for student in payload['students'] for identifier in student['evidence_ids']})
    else:
        result['citable_source_ids'] = list(payload.get('evidence_ids', []))
    return result


def compact_handoff(handoff):
    """Keep exact requirements/ownership edges, intern repeated evidence once."""
    result = deepcopy(handoff)
    registry = {}
    for source in result['source_map'].values():
        refs = []
        for evidence in source.pop('evidence'):
            ref = evidence['paper']['paper_id'] + ':' + digest(evidence)[:16]
            registry[ref] = evidence
            refs.append(ref)
        source['evidence_refs'] = refs
    result['evidence_registry'] = registry
    return result
