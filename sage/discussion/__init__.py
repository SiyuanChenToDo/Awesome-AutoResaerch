# CoI-Agent chain ideation (Apache-2.0) + Agent Laboratory role discussions (MIT).
# MODIFIED for SAGE 2026-10-17: owned bounded discussion and traceable plan handoff.
"""Structural grounding checks cannot establish semantic support or scientific truth."""
from copy import deepcopy
from dataclasses import asdict
import json
import hashlib
from ..errors import InvalidResponse, ValidationError, NoEvidence, SageError, BudgetExceeded
from ..types import NoveltyAssessment, paper_record
from .prompts import prompt

ROLES = ('methods and mechanisms', 'evaluation and counterexamples', 'robustness and transfer', 'feasibility and reproducibility')


def strict_object(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValidationError('duplicate_key')
            out[key] = value
        return out
    try:
        value = json.loads(text, object_pairs_hook=pairs)
    except (ValueError, TypeError):
        raise ValidationError('json_object') from None
    if not isinstance(value, dict):
        raise ValidationError('json_object')
    return value


def fields(value, schema):
    if set(value) != set(schema):
        raise ValidationError('schema_keys')
    for key, kind in schema.items():
        item = value[key]
        if kind == 'text' and (not isinstance(item, str) or not item.strip()):
            raise ValidationError('nonempty_text', key)
        if kind == 'ids' and (not isinstance(item, list) or any(not isinstance(x, str) or not x for x in item) or len(item) != len(set(item))):
            raise ValidationError('unique_ids', key)
        if kind == 'index' and type(item) is not int:
            raise ValidationError('integer_index', key)
        if kind == 'requirements' and not isinstance(item, list):
            raise ValidationError('list_required', key)


def evidence_ids(value, allowed, *, required=True):
    if (required and not value) or not set(value) <= set(allowed):
        raise ValidationError('source_ownership', 'evidence_ids')

REVISION_SCHEMA = {'idea': 'text', 'evidence_ids': 'ids', 'accepted_critique_ids': 'ids',
                   'rejected_critique_ids': 'ids', 'rationale': 'text', 'uncertainty': 'text'}

def validate_revision(v, *, original_idea, own_evidence_ids, targeted, prior,
                      shared_evidence_ids=None, allow_methodological=False, canonical_controls=False):
    """Pure replayable validator. Never rewrites returned values."""
    fields(v, REVISION_SCHEMA)
    allowed = {c['critique_id']: c for c in targeted if c['status'] == 'supported' or
               (allow_methodological and c['status'] == 'methodological')}
    reported_accepted, rejected = set(v['accepted_critique_ids']), set(v['rejected_critique_ids'])
    # v3 accepts either current-round or cumulative approved IDs. Previously
    # approved IDs never become new decisions, and cannot be silently revoked.
    accepted = reported_accepted - set(prior) if canonical_controls else reported_accepted
    if canonical_controls and not reported_accepted <= set(allowed) | set(prior):
        raise ValidationError('revision_decisions', 'accepted_critique_ids')
    if not accepted <= set(allowed) or accepted & rejected or accepted | rejected != {c['critique_id'] for c in targeted}:
        raise ValidationError('revision_decisions', 'accepted_critique_ids')
    adopted = {**prior, **{k: allowed[k] for k in accepted}}
    evidence_ids(v['evidence_ids'], set(shared_evidence_ids if shared_evidence_ids is not None else own_evidence_ids) |
                 {e for c in adopted.values() for e in c['evidence_ids']})
    if not accepted and v['idea'] != original_idea and not (canonical_controls and v['idea'] == 'UNCHANGED'):
        raise ValidationError('unchanged_idea', 'idea')
    if accepted and (v['idea'] == original_idea or (canonical_controls and v['idea'] == 'UNCHANGED')):
        raise ValidationError('changed_idea', 'idea')
    if not canonical_controls and any(c['requested_change'] not in v['idea'] for c in adopted.values()):
        raise ValidationError('verbatim_requirement', 'idea')
    if not canonical_controls and any(not set(c['evidence_ids']) <= set(v['evidence_ids']) for c in adopted.values()):
        raise ValidationError('retained_evidence', 'evidence_ids')


def publish_controls(proposal_text, controls):
    """Attach only explicitly adopted, ledger-owned requirements, exactly once.

    The model edits narrative; it cannot add/remove the authoritative control set.
    This preserves exact requirements without demanding long verbatim model copies.
    """
    marker = '\n\n[SAGE_ACCEPTED_CONTROLS]'
    narrative = proposal_text.split(marker, 1)[0]
    if not controls:
        return narrative
    return narrative + marker + '\n' + '\n'.join(
        '[' + c['critique_id'] + '] ' + c['requested_change'] for c in controls
    ) + '\n[/SAGE_ACCEPTED_CONTROLS]'


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
                           student_id=payload.get('student_id'), prompt_chars=len(text),
                           original_payload_chars=len(json.dumps(payload, ensure_ascii=False)),
                           context_protocol='sage.discussion.context.v2')
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
        shared = self.runtime.config.discussion_prompt_version == 'v3'
        evidence_library = {e.paper.paper_id: e for c in candidates for e in c.chain.evidence}
        if shared:
            evidence_library.update(getattr(self.runtime, 'evidence_cards', {}))
        shared_evidence = [asdict(e) for e in evidence_library.values()]
        shared_ids = {e['paper']['paper_id'] for e in shared_evidence}
        source_owners = {identity: [f'phd-{i+1}' for i, portfolio in enumerate(portfolios) if identity in portfolio]
                         for identity in shared_ids}
        source_owners = {identity: owners or ['supplemental_literature_review'] for identity, owners in source_owners.items()}
        extra = {'shared_evidence': shared_evidence, 'source_owners': source_owners,
                 'canonical_controls_managed': True} if shared else {}
        if shared:
            self.ledger['shared_source_owners'] = source_owners
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
            if shared:
                student['proposal_text'] = value['idea']
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
                payload.update(extra)
                def validate(v):
                    if v['status'] not in (('supported', 'methodological', 'unknown') if shared else ('supported', 'unknown')):
                        raise ValidationError('critique_status', 'status')
                    evidence_ids(v['evidence_ids'], shared_ids if shared else student['evidence_ids'], required=v['status'] == 'supported')
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
                allowed = {c['critique_id']: c for c in targeted if c['status'] == 'supported' or
                           (shared and c['status'] == 'methodological')}
                prior = {c['critique_id']: c for c in self.ledger['critiques'] if c['critique_id'] in student['accepted_critique_ids']}
                available = set(student['evidence_ids']) | {e for c in [*allowed.values(), *prior.values()] for e in c['evidence_ids']}
                payload = {'round': number, 'student_id': student['student_id'], 'candidate': snapshots[i],
                           'critiques': targeted, 'prior_accepted_critiques': list(prior.values()), 'evidence_ids': sorted(available),
                           'peer_evidence': [snapshots[j]['chain']['evidence'] for j in range(count) if j != i]}
                payload.update(extra)
                if shared:
                    payload['proposal_text'] = student['proposal_text']
                def validate(v):
                    validate_revision(v, original_idea=student['proposal_text'] if shared else candidates[i].idea,
                                      own_evidence_ids=student['evidence_ids'], targeted=targeted, prior=prior,
                                      shared_evidence_ids=shared_ids if shared else None, allow_methodological=shared,
                                      canonical_controls=shared)
                value = await self.ask('revise', payload, REVISION_SCHEMA, validate)
                student['revisions'].append({'round': number, 'previous_idea': candidates[i].idea, **value})
                student['accepted_critique_ids'].extend(c for c in value['accepted_critique_ids'] if c not in student['accepted_critique_ids'])
                if shared:
                    if value['idea'] != 'UNCHANGED':
                        student['proposal_text'] = value['idea']
                    adopted = [c for c in self.ledger['critiques'] if c['critique_id'] in student['accepted_critique_ids']]
                    candidates[i].idea = publish_controls(student['proposal_text'], adopted)
                    student['revisions'][-1]['published_idea'] = candidates[i].idea
                    student['revisions'][-1]['published_evidence_ids'] = sorted(set(value['evidence_ids']) |
                        {identity for c in adopted for identity in c['evidence_ids']})
                else:
                    candidates[i].idea = value['idea']
        # Recheck revised ideas without claiming that initial novelty assessments carry over.
        for candidate in candidates:
            candidate.novelty = await review.novelty(candidate.idea, topic)
        payload = {'topic': topic, 'students': self.ledger['students'], 'candidates': [asdict(c) for c in candidates],
                   'critiques': self.ledger['critiques']}
        payload.update(extra)
        def validate(v):
            if not 0 <= v['selected_index'] < count:
                raise ValidationError('selection_range', 'selected_index')
            accepted = self.ledger['students'][v['selected_index']]['accepted_critique_ids']
            if set(v['accepted_critique_ids']) != set(accepted):
                raise ValidationError('accepted_critique_set', 'accepted_critique_ids')
            if shared:
                if v['requirements']:
                    raise ValidationError('canonical_requirements_managed', 'requirements')
                return
            seen = []
            for requirement in v['requirements']:
                if not isinstance(requirement, dict):
                    raise ValidationError('requirement_shape', 'requirements')
                fields(requirement, {'critique_id': 'text', 'requirement': 'text'})
                matching = next((c for c in self.ledger['critiques'] if c['critique_id'] == requirement['critique_id']), None)
                if matching is None or requirement['requirement'] != matching['requested_change']:
                    raise ValidationError('canonical_requirement', 'requirements')
                seen.append(requirement['critique_id'])
            if len(seen) != len(set(seen)) or set(seen) != set(accepted):
                raise ValidationError('requirements_coverage', 'requirements')
        value = await self.ask('synthesize', payload, {'selected_index': 'index', 'rationale': 'text',
                      'accepted_critique_ids': 'ids', 'requirements': 'requirements', 'uncertainty': 'text'}, validate)
        if shared:
            value['requirements'] = [{'critique_id':c['critique_id'],'requirement':c['requested_change']}
                                    for c in self.ledger['critiques'] if c['critique_id'] in value['accepted_critique_ids']]
        self.ledger['synthesis'] = value
        all_sources = {e.paper.paper_id: {'paper': paper_record(e.paper), 'idea': e.idea,
                      'experiment': e.experiment, 'entities': e.entities, 'capsule': e.capsule}
                       for e in evidence_library.values()}
        sources = {student['student_id']: (all_sources if shared else {e.paper.paper_id: {'paper': paper_record(e.paper), 'idea': e.idea,
                    'experiment': e.experiment, 'entities': e.entities} for e in candidates[student['candidate_index']].chain.evidence})
                   for student in self.ledger['students']}
        self.ledger['plan_handoff'] = {'candidate_index': value['selected_index'],
            'accepted_critique_ids': value['accepted_critique_ids'], 'requirements': value['requirements'],
            'source_map': {c['critique_id']: {'author_id': c['author_id'], 'evidence_ids': c['evidence_ids'],
                                                'evidence': [sources[c['author_id']][e] for e in c['evidence_ids']]}
                           for c in self.ledger['critiques'] if c['critique_id'] in value['accepted_critique_ids']}}
        self.ledger['status'] = 'completed_with_uncertainty' if any(c['status'] in ('unknown','failed') for c in self.ledger['critiques']) else 'completed'
        return value['selected_index']

    def bind_plan(self, plan):
        handoff = deepcopy(self.ledger['plan_handoff'])
        # Preserve requirements even if the model's later free-text refinement omits them.
        requirements = '\n'.join(f"[{r['critique_id']}] {r['requirement']}" for r in handoff['requirements'])
        plan.revisions.append({'stage': 'discussion_handoff', 'previous_proposal': plan.proposal, 'handoff': handoff})
        if requirements:
            plan.proposal += '\n\nMandatory discussion-derived proposal controls (unexecuted):\n' + requirements
        self.ledger['plan_handoff']['bound_to_plan'] = True
