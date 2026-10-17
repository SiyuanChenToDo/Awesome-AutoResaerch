"""Lossless evidence interning and task-specific views; full history stays in ledger."""
from copy import deepcopy
from ..checkpoints import digest
import json


def capsule_view(capsule, limit=4500):
    """All roles see every source; each task view discloses omitted claim detail."""
    card = deepcopy(capsule)
    count = len(card.get('claims', []))
    card['full_capsule_sha256'] = digest(capsule)
    card['view_omitted_claims'] = 0
    card['inferences_unverified'] = []  # Not primary evidence for another role.
    card['view_scope'] = 'Task projection; complete capsule and inferences remain in run ledger.'
    while len(json.dumps(card, ensure_ascii=False)) > limit and card.get('claims'):
        card['claims'].pop()
        card['view_omitted_claims'] = count-len(card['claims'])
    return card


def compact_payload(stage, payload, *, shared=False):
    result = deepcopy(payload)
    if stage == 'critique' and not shared:
        # A reviewer critiques the target idea against its OWN sources. Merely
        # showing all peer papers both wastes context and blurs source ownership.
        target = result['target_candidate']
        target['chain']['evidence'] = [
            {'paper': {'paper_id': evidence['paper']['paper_id'],
                       'evidence_scope': evidence['paper'].get('evidence_scope')},
             'view_scope': 'Target source identity only; not supplied as citable evidence.'}
            for evidence in target['chain']['evidence']]
        target['chain'] = {key: value for key, value in target['chain'].items()
                           if key in ('evidence', 'relation')}
    elif stage == 'revise' and not shared:
        allowed_peer = {identity for critique in payload['critiques']
                        if critique['status'] == 'supported' for identity in critique['evidence_ids']}
        allowed_peer.update(identity for critique in payload['prior_accepted_critiques']
                            for identity in critique['evidence_ids'])
        result['peer_evidence'] = [[e for e in chain if e['paper']['paper_id'] in allowed_peer]
                                   for chain in result.get('peer_evidence', [])]
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
    per_source_limit = min(4500, max(2000, 90000 // max(1, len(payload.get('shared_evidence', [])))))

    def intern(value):
        if isinstance(value, list):
            return [intern(x) for x in value]
        if not isinstance(value, dict):
            return value
        if 'paper' in value and isinstance(value['paper'], dict) and 'idea' in value and 'experiment' in value:
            identity = value['paper']['paper_id']
            # Different extractions of one paper must not overwrite each other.
            ref = identity + ':' + digest(value)[:16]
            if value.get('capsule'):
                registry[ref] = {'paper': {k: v for k,v in value['paper'].items() if k not in ('article','abstract')},
                                 'capsule': capsule_view(value['capsule'], per_source_limit),
                                 'references': value.get('references', []), 'full_evidence_sha256':digest(value),
                                 'view_scope':'Scoped source excerpts, not raw full paper or repeated abstract.'}
            elif stage in ('synthesize', 'report'):
                # Selection/writing get exact primary source text. Generated
                # interpretations remain in the ledger and still reach the
                # experiment-design module, without duplicating the proposal.
                record = {k: v for k, v in value.items() if k in ('paper', 'references', 'capsule')}
                record['full_evidence_sha256'] = digest(value)
                record['view_scope'] = 'Exact primary source text; generated idea/experiment/entity interpretations omitted from this task view.'
                registry[ref] = record
            else:
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
            novelty = value['novelty']
            compared = novelty.get('compared_papers', [])
            value['novelty'] = {**{k: v for k, v in novelty.items() if k != 'compared_papers'},
                'compared_papers': [{k: paper[k] for k in ('paper_id', 'title', 'url', 'evidence_scope') if k in paper}
                                    for paper in compared],
                'comparison_history_sha256': digest(compared),
                'comparison_scope': 'Source identities and prior model assessment only; full retrieved comparison text is retained in the ledger.'}
            if stage in ('critique', 'revise', 'synthesize', 'report'):
                value.pop('future', None)
                value.pop('human_considerations', None)
            if stage in ('synthesize', 'report'):
                value['chain'] = {k: v for k, v in value['chain'].items() if k not in ('trend', 'entities')}
                value['chain']['view_scope'] = 'Primary sources and current proposal; generated trend/entity summaries retained in the ledger.'
        return {k: intern(v) for k, v in value.items()}

    result = intern(result)
    result['evidence_registry'] = registry
    result['context_policy'] = ('Evidence stubs resolve to task-scoped records in evidence_registry; obey each view_scope. '
        'History is retained in the audit ledger; do not infer unseen history. '
        'Only top-level citable_source_ids authorize citations in your response; '
        'a source appearing in another role or target does not authorize its use.')
    if shared:
        result['citable_source_ids'] = sorted({e['paper']['paper_id'] for e in payload.get('shared_evidence', [])})
        if not result['citable_source_ids']:
            result['citable_source_ids'] = list(payload.get('evidence_ids', []))
        result['context_policy'] = ('All supplied shared_evidence cards are citable by any role. '
            'source_owners records discovery provenance, not exclusive citation permission. '
            'Cite exact excerpts/locators; source claims and methodological proposals are different. '
            'Do not treat metadata, inference or missing text as empirical evidence.')
    elif stage == 'critique':
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
