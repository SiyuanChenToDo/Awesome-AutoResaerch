# CoI-Agent chain ideation (Apache-2.0) + Agent Laboratory role discussions (MIT).
# MODIFIED for SAGE 2026-10-17: owned bounded discussion and traceable plan handoff.
"""Structural grounding checks cannot establish semantic support or scientific truth."""
from copy import deepcopy
from dataclasses import asdict
import json
import hashlib
from ..errors import InvalidResponse, NoEvidence, SageError, BudgetExceeded
from ..types import NoveltyAssessment, paper_record
from .prompts import prompt

ROLES = ('methods and mechanisms', 'evaluation and counterexamples', 'robustness and transfer', 'feasibility and reproducibility')


def strict_object(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise InvalidResponse('Duplicate discussion JSON key')
            out[key] = value
        return out
    try:
        value = json.loads(text, object_pairs_hook=pairs)
    except (ValueError, TypeError):
        raise InvalidResponse('Discussion requires JSON object') from None
    if not isinstance(value, dict):
        raise InvalidResponse('Discussion requires JSON object')
    return value


def fields(value, schema):
    if set(value) != set(schema):
        raise InvalidResponse('Discussion schema keys mismatch')
    for key, kind in schema.items():
        item = value[key]
        if kind == 'text' and (not isinstance(item, str) or not item.strip()):
            raise InvalidResponse('Discussion requires nonempty text')
        if kind == 'ids' and (not isinstance(item, list) or any(not isinstance(x, str) or not x for x in item) or len(item) != len(set(item))):
            raise InvalidResponse('Discussion requires unique string IDs')
        if kind == 'index' and type(item) is not int:
            raise InvalidResponse('Discussion requires integer index')
        if kind == 'requirements' and not isinstance(item, list):
            raise InvalidResponse('Discussion requirements must be a list')


def evidence_ids(value, allowed, *, required=True):
    if (required and not value) or not set(value) <= set(allowed):
        raise InvalidResponse('Discussion evidence outside assigned source ownership')


class Discussion:
    def __init__(self, runtime):
        self.runtime = runtime
        self.ledger = {'schema_version': 'sage.discussion.v1', 'status': 'running',
                       'students': [], 'critiques': [], 'prompt_history': [],
                       'synthesis': None, 'plan_handoff': None,
                       'limitations': 'Shared model roles; structural citations only, not independent experts or semantic verification.'}

    async def ask(self, stage, payload, schema, validate):
        version = self.runtime.config.discussion_prompt_version
        text, digest = prompt(stage, payload, schema, version)
        self.runtime.event('discussion.prompt', 'recorded', task=stage, version=version, template_sha256=digest,
                           input_sha256=hashlib.sha256(text.encode()).hexdigest(), round=payload.get('round', 0),
                           student_id=payload.get('student_id'))
        self.ledger['prompt_history'].append({'stage': stage, 'version': version, 'template_sha256': digest,
            'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'round': payload.get('round', 0), 'student_id': payload.get('student_id'),
            'revision_policy': 'fixed versioned template; bounded evidence/critique feedback, no self-editing'})
        def check(response):
            obj = strict_object(response['discussion'])
            fields(obj, schema)
            validate(obj)
        response = await self.runtime.ask('discussion.' + stage, text, ('discussion',), validate=check)
        return strict_object(response['discussion'])

    async def deliberate(self, candidates, topic, review):
        count = self.runtime.config.discussion_students
        if len(candidates) != count:
            raise NoEvidence('Hybrid discussion requires the configured number of distinct student chains')
        portfolios = [{e.paper.paper_id for e in c.chain.evidence} for c in candidates]
        if any(not (p - set().union(*(q for j, q in enumerate(portfolios) if j != i))) for i, p in enumerate(portfolios)):
            raise NoEvidence('Each hybrid student needs at least one exclusive source; duplicated portfolios are insufficient')
        for i, candidate in enumerate(candidates):
            student = {'student_id': f'phd-{i+1}', 'role': ROLES[i], 'candidate_index': i,
                       'evidence_ids': sorted(portfolios[i]), 'original_candidate': deepcopy(asdict(candidate)),
                       'revisions': [], 'accepted_critique_ids': []}
            self.ledger['students'].append(student)
            payload = {'topic': topic, 'student_id': student['student_id'], 'role': student['role'],
                       'candidate': asdict(candidate), 'evidence_ids': student['evidence_ids']}
            value = await self.ask('develop', payload, {'idea': 'text', 'evidence_ids': 'ids', 'rationale': 'text', 'uncertainty': 'text'},
                                   lambda v: evidence_ids(v['evidence_ids'], portfolios[i]))
            student['development'] = value
            candidate.idea = value['idea']
            candidate.novelty = NoveltyAssessment('not_established', [], [], 'Discussion changed proposal; novelty has not been rechecked.')
        for number in range(1, self.runtime.config.discussion_rounds + 1):
            # Snapshot all ideas before the ring so later reviewers cannot see earlier revisions.
            snapshots = [asdict(c) for c in candidates]
            current = []
            for i, student in enumerate(self.ledger['students']):
                target = (i + 1) % count
                critique = {'critique_id': f'r{number}-{student["student_id"]}-to-phd-{target+1}',
                            'author_id': student['student_id'], 'target_id': f'phd-{target+1}', 'round': number}
                payload = {'round': number, 'student_id': student['student_id'], 'role': student['role'],
                           'own_candidate': snapshots[i], 'evidence_ids': student['evidence_ids'],
                           'target_id': critique['target_id'], 'target_candidate': snapshots[target]}
                def validate(v):
                    if v['status'] not in ('supported', 'unknown'):
                        raise InvalidResponse('Invalid critique status')
                    evidence_ids(v['evidence_ids'], student['evidence_ids'], required=v['status'] == 'supported')
                try:
                    value = await self.ask('critique', payload, {'status': 'text', 'evidence_ids': 'ids', 'issue': 'text',
                        'requested_change': 'text', 'support': 'text', 'uncertainty': 'text'}, validate)
                    critique.update(value)
                except BudgetExceeded:
                    raise
                except SageError as error:
                    critique.update(status='failed', evidence_ids=[], issue='Critique failed contract/provider validation',
                                    requested_change='', support='', uncertainty='Unknown', error_code=error.code)
                self.ledger['critiques'].append(critique)
                current.append(critique)
            for i, student in enumerate(self.ledger['students']):
                targeted = [c for c in current if c['target_id'] == student['student_id']]
                allowed = {c['critique_id']: c for c in targeted if c['status'] == 'supported'}
                prior = {c['critique_id']: c for c in self.ledger['critiques'] if c['critique_id'] in student['accepted_critique_ids']}
                available = set(student['evidence_ids']) | {e for c in [*allowed.values(), *prior.values()] for e in c['evidence_ids']}
                payload = {'round': number, 'student_id': student['student_id'], 'candidate': snapshots[i],
                           'critiques': targeted, 'prior_accepted_critiques': list(prior.values()), 'evidence_ids': sorted(available),
                           'peer_evidence': [snapshots[j]['chain']['evidence'] for j in range(count) if j != i]}
                def validate(v):
                    accepted, rejected = set(v['accepted_critique_ids']), set(v['rejected_critique_ids'])
                    if not accepted <= set(allowed) or accepted & rejected or accepted | rejected != {c['critique_id'] for c in targeted}:
                        raise InvalidResponse('Revision must decide all critiques and cannot accept unknown/failed critiques')
                    adopted = {**prior, **{k: allowed[k] for k in accepted}}
                    evidence_ids(v['evidence_ids'], set(student['evidence_ids']) | {e for c in adopted.values() for e in c['evidence_ids']})
                    if not accepted and v['idea'] != candidates[i].idea:
                        raise InvalidResponse('Unaccepted critique cannot change proposal')
                    if accepted and v['idea'] == candidates[i].idea:
                        raise InvalidResponse('Accepted critique requires a changed proposal')
                    if any(c['requested_change'] not in v['idea'] for c in adopted.values()):
                        raise InvalidResponse('Accepted critique change must appear verbatim in revised proposal')
                    if any(not set(c['evidence_ids']) <= set(v['evidence_ids']) for c in adopted.values()):
                        raise InvalidResponse('Accepted critique must retain its cited evidence')
                value = await self.ask('revise', payload, {'idea': 'text', 'evidence_ids': 'ids', 'accepted_critique_ids': 'ids',
                      'rejected_critique_ids': 'ids', 'rationale': 'text', 'uncertainty': 'text'}, validate)
                student['revisions'].append({'round': number, 'previous_idea': candidates[i].idea, **value})
                student['accepted_critique_ids'].extend(value['accepted_critique_ids'])
                candidates[i].idea = value['idea']
        # Recheck revised ideas without claiming that initial novelty assessments carry over.
        for candidate in candidates:
            candidate.novelty = await review.novelty(candidate.idea, topic)
        payload = {'topic': topic, 'students': self.ledger['students'], 'candidates': [asdict(c) for c in candidates],
                   'critiques': self.ledger['critiques']}
        def validate(v):
            if not 0 <= v['selected_index'] < count:
                raise InvalidResponse('Postdoc selection outside student candidates')
            accepted = self.ledger['students'][v['selected_index']]['accepted_critique_ids']
            if set(v['accepted_critique_ids']) != set(accepted):
                raise InvalidResponse('Postdoc must preserve selected student accepted critiques')
            seen = []
            for requirement in v['requirements']:
                if not isinstance(requirement, dict):
                    raise InvalidResponse('Malformed plan requirement')
                fields(requirement, {'critique_id': 'text', 'requirement': 'text'})
                matching = next((c for c in self.ledger['critiques'] if c['critique_id'] == requirement['critique_id']), None)
                if matching is None or requirement['requirement'] != matching['requested_change']:
                    raise InvalidResponse('Plan requirement must preserve canonical accepted change')
                seen.append(requirement['critique_id'])
            if len(seen) != len(set(seen)) or set(seen) != set(accepted):
                raise InvalidResponse('Every accepted critique requires one traceable planning requirement')
        value = await self.ask('synthesize', payload, {'selected_index': 'index', 'rationale': 'text',
                      'accepted_critique_ids': 'ids', 'requirements': 'requirements', 'uncertainty': 'text'}, validate)
        self.ledger['synthesis'] = value
        sources = {student['student_id']: {e.paper.paper_id: {'paper': paper_record(e.paper), 'idea': e.idea,
                    'experiment': e.experiment, 'entities': e.entities} for e in candidates[student['candidate_index']].chain.evidence}
                   for student in self.ledger['students']}
        self.ledger['plan_handoff'] = {'candidate_index': value['selected_index'],
            'accepted_critique_ids': value['accepted_critique_ids'], 'requirements': value['requirements'],
            'source_map': {c['critique_id']: {'author_id': c['author_id'], 'evidence_ids': c['evidence_ids'],
                                                'evidence': [sources[c['author_id']][e] for e in c['evidence_ids']]}
                           for c in self.ledger['critiques'] if c['critique_id'] in value['accepted_critique_ids']}}
        self.ledger['status'] = 'completed_with_uncertainty' if any(c['status'] != 'supported' for c in self.ledger['critiques']) else 'completed'
        return value['selected_index']

    def bind_plan(self, plan):
        handoff = deepcopy(self.ledger['plan_handoff'])
        # Preserve requirements even if the model's later free-text refinement omits them.
        requirements = '\n'.join(f"[{r['critique_id']}] {r['requirement']}" for r in handoff['requirements'])
        plan.revisions.append({'stage': 'discussion_handoff', 'previous_proposal': plan.proposal, 'handoff': handoff})
        if requirements:
            plan.proposal += '\n\nMandatory discussion-derived proposal controls (unexecuted):\n' + requirements
        self.ledger['plan_handoff']['bound_to_plan'] = True
