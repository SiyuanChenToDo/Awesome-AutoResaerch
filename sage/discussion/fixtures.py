"""Causal deterministic discussion fake, not a real-model quality evaluation.

Responses consume each prompt's owned evidence, critiques and decisions; removing
or changing a critique changes revision, selection and planning requirements.
"""
import json


def respond(stage, prompt):
    payload = json.loads(prompt.split('INPUT_JSON:\n', 1)[1])
    if stage == 'discussion.develop':
        value = {'idea': payload['candidate']['idea'] + ' Student focus: ' + payload['role'] + '.',
                 'evidence_ids': payload['evidence_ids'],
                 'rationale': 'Synthetic chain motivates a falsifiable, controlled comparison; no measured effect.',
                 'uncertainty': 'Synthetic sources do not establish effectiveness or novelty.'}
    elif stage == 'discussion.critique':
        supported = payload['student_id'] == 'phd-1'
        value = {'status': 'supported' if supported else 'unknown',
                 'evidence_ids': payload['evidence_ids'][:1] if supported else [],
                 'issue': 'Search effort could confound the proposed method comparison.' if supported else 'Transfer to real-world tasks is unestablished.',
                 'requested_change': 'Add a matched-budget ablation separating method change from search effort.' if supported else 'Claim transfer improvement.',
                 'support': 'Assigned synthetic chain describes controlled evaluation; the ablation is a proposed control, not a measured result.' if supported else 'No supplied empirical transfer evidence.',
                 'uncertainty': 'This is synthetic fixture advice; actual scientific support needs human review.'}
    elif stage == 'discussion.revise':
        accepted = [c for c in payload['critiques'] if c['status'] == 'supported']
        own_ids = [e['paper']['paper_id'] for e in payload['candidate']['chain']['evidence']]
        value = {'idea': payload['candidate']['idea'] + ''.join('\n' + c['requested_change'] for c in accepted),
                 'evidence_ids': sorted(set(own_ids) | {e for c in accepted + payload['prior_accepted_critiques'] for e in c['evidence_ids']}),
                 'accepted_critique_ids': [c['critique_id'] for c in accepted],
                 'rejected_critique_ids': [c['critique_id'] for c in payload['critiques'] if c not in accepted],
                 'rationale': 'Add only source-scoped proposed controls; reject unsupported improvement claims.',
                 'uncertainty': 'No empirical result is established.'}
    elif stage == 'discussion.synthesize':
        # A scripted fixture decision policy demonstrates causal integration, not best research selection.
        selected = max(range(len(payload['students'])), key=lambda i: (len(payload['students'][i]['accepted_critique_ids']), -i))
        accepted = payload['students'][selected]['accepted_critique_ids']
        value = {'selected_index': selected, 'accepted_critique_ids': accepted,
                 'requirements': [{'critique_id': c['critique_id'], 'requirement': c['requested_change']}
                                  for c in payload['critiques'] if c['critique_id'] in accepted],
                 'rationale': 'Fixture policy favors explicitly adopted source-scoped controls, with stable tie breaking.',
                 'uncertainty': 'Fixture selection demonstrates wiring only, not superior scientific quality.'}
    else:
        raise ValueError('Unknown fixture discussion stage')
    return '<discussion>' + json.dumps(value) + '</discussion>'
