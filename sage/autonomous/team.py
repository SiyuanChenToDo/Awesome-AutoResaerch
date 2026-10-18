"""Manager-owned, snapshot-based coordination of real native researchers.

This is a software collaboration contract, not a scientific quality evaluator.
The service authenticates native identities and source IDs and reads each primary
artifact; the board enforces exchange barriers and keeps immutable submissions.
It records submitted scientific documents and decisions, never model reasoning.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from datetime import datetime, timezone

from ..artifacts import atomic_json


ROLES = (
    'methods and mechanisms',
    'evaluation and counterexamples',
    'robustness and transfer',
    'feasibility and reproducibility',
)
_SCIENTIFIC_FIELDS = ('problem', 'hypothesis', 'mechanism', 'assumptions',
                      'closest_prior_art', 'falsification', 'risks', 'source_ids')


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be a nonempty string')
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Expected an exact lowercase SHA-256 primary artifact hash')
    return value


def _sources(value):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError('source_ids must be a list of nonempty source IDs')
    if len(set(value)) != len(value):
        raise ValueError('source_ids must not contain duplicates')


def _candidates(document):
    if not isinstance(document, dict) or not isinstance(document.get('candidates'), list):
        raise ValueError('Document must contain a candidates list')
    result = {}
    for item in document['candidates']:
        if not isinstance(item, dict):
            raise ValueError('Every candidate must be an object')
        ident = _text(item.get('id'), 'Candidate id')
        if ident in result:
            raise ValueError('Candidate IDs must be unique within a document')
        result[ident] = item
    if not result:
        raise ValueError('At least one candidate is required')
    # Validate JSON serializability and finite numeric values before persistence.
    _canonical(document)
    return result


def _scientific_content(candidate):
    """Exclude acknowledgements, titles and provenance from repair detection.

    Non-identical content still does not establish semantic correctness. A new
    source or an explicit, justified rejection can be a substantive response.
    """
    result = {key: candidate[key] for key in _SCIENTIFIC_FIELDS if key in candidate}
    sources = result.get('source_ids')
    if isinstance(sources, list) and all(isinstance(value, str) for value in sources):
        result['source_ids'] = sorted(set(sources))
    reason = candidate.get('rejection_reason')
    if (candidate.get('disposition') == 'rejected'
            and isinstance(reason, str) and reason.strip()):
        result['rejection'] = {'disposition': 'rejected', 'reason': reason}
    return result


class TeamBoard:
    """A single manager's durable board; public methods are thread-safe.

    A native process must register an actual distinct session/worktree identity
    before using the service. Identity authentication and file confinement belong
    to the caller. The private directory must be owned by the manager account.
    Multiple operating-system processes must not independently mutate this board.
    """

    def __init__(self, private, slots=4, rounds=2):
        if type(slots) is not int or not 2 <= slots <= len(ROLES):
            raise ValueError('Team slots must be an integer between two and four')
        if type(rounds) is not int or not 1 <= rounds <= 8:
            raise ValueError('Review rounds must be an integer between one and eight')
        self.private = Path(private)
        if self.private.is_symlink():
            raise ValueError('Team private directory must not be a symlink')
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == 'posix' and self.private.stat().st_uid != os.geteuid():
            raise ValueError('Team private directory must be manager-owned')
        self.private.chmod(0o700)
        self.path = self.private / 'team-state.json'
        if self.path.is_symlink():
            raise ValueError('Team state must not be a symlink')
        self.lock = threading.RLock()
        if self.path.exists():
            if not self.path.is_file():
                raise ValueError('Team state must be a regular file')
            if os.name == 'posix' and self.path.stat().st_uid != os.geteuid():
                raise ValueError('Team state must be manager-owned')
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
            if (self.state.get('schema_version') != 'sage.autonomous.team.v1'
                    or self.state.get('slots') != slots or self.state.get('round_count') != rounds):
                raise ValueError('Existing team state does not match this team configuration')
            self.path.chmod(0o600)
        else:
            self.state = {'schema_version': 'sage.autonomous.team.v1', 'slots': slots,
                          'round_count': rounds, 'roster': {}, 'proposals': {},
                          'rounds': {}, 'syntheses': [], 'events': []}
            self._save()
        self.slots, self.rounds = slots, rounds

    def _save(self):
        atomic_json(self.path, self.state)

    def _slot(self, slot, *, registered=True):
        if type(slot) is not int or not 0 <= slot < self.slots:
            raise ValueError('Unknown team slot')
        if registered and str(slot) not in self.state['roster']:
            raise ValueError('Native agent identity must register before team operations')
        return str(slot)

    def _phase(self):
        if len(self.state['proposals']) < self.slots:
            return 'proposing', 0
        for number in range(1, self.rounds + 1):
            record = self.state['rounds'].get(str(number), {})
            if len(record.get('reviews', {})) < self.slots:
                return 'reviewing', number
            if len(record.get('revisions', {})) < self.slots:
                return 'revising', number
        return ('complete' if self.state['syntheses'] else 'synthesizing'), self.rounds

    def _round(self, number):
        return self.state['rounds'].setdefault(str(number), {'reviews': {}, 'revisions': {}})

    def _frozen(self, number):
        return (self.state['proposals'] if number == 1
                else self.state['rounds'][str(number - 1)]['revisions'])

    def _receipt(self, operation, slot, payload, **fields):
        receipt = {'operation': operation, 'slot': slot, 'payload_sha256': _digest(payload),
                   'sequence': len(self.state['events']) + 1,
                   'time': datetime.now(timezone.utc).isoformat(), **fields}
        self.state['events'].append(copy.deepcopy(receipt))
        return receipt

    @staticmethod
    def _retry(record, payload):
        if record['receipt']['payload_sha256'] == _digest(payload):
            return copy.deepcopy(record['receipt'])
        raise ValueError('A frozen submission already exists; it cannot be overwritten')

    def register(self, slot, agent_id, cwd, session_id):
        """Bind one slot to one actual runtime identity; identical retries are safe."""
        with self.lock:
            key = self._slot(slot, registered=False)
            agent_id, session_id = _text(agent_id, 'agent_id'), _text(session_id, 'session_id')
            if not isinstance(cwd, (str, os.PathLike)) or not str(cwd).strip():
                raise ValueError('cwd must identify the native agent worktree')
            cwd = str(Path(cwd).resolve())
            payload = {'agent_id': agent_id, 'cwd': cwd, 'session_id': session_id}
            if key in self.state['roster']:
                return self._retry(self.state['roster'][key], payload)
            for identity in self.state['roster'].values():
                if any(identity[name] == payload[name] for name in ('agent_id', 'cwd', 'session_id')):
                    raise ValueError('Each slot requires a distinct native agent, worktree and session')
            receipt = self._receipt('register', slot, payload, role=ROLES[slot])
            self.state['roster'][key] = {**payload, 'role': ROLES[slot], 'receipt': receipt}
            self._save()
            return copy.deepcopy(receipt)

    def status(self, slot=None):
        with self.lock:
            result = self.summary()
            if slot is None:
                return result
            key = self._slot(slot)
            phase, number = self._phase()
            action, target = 'wait', None
            if phase == 'proposing' and key not in self.state['proposals']:
                action = 'propose'
            elif phase == 'reviewing' and key not in self._round(number)['reviews']:
                action, target = 'review', (slot + 1 + (number - 1) % (self.slots - 1)) % self.slots
            elif phase == 'revising' and key not in self._round(number)['revisions']:
                action = 'revise'
            elif phase in ('synthesizing', 'complete'):
                action = 'synthesize' if slot == 0 else 'finished'
            result.update({'slot': slot, 'role': ROLES[slot], 'next_action': action,
                           'review_target': target})
            if target is not None:
                result['target_primary_sha256'] = self._frozen(number)[str(target)]['primary_sha256']
            return result

    def snapshot(self, slot):
        """Reveal only all-agent frozen phases, never partially submitted peers."""
        with self.lock:
            key = self._slot(slot)
            result = self.status(slot)
            phase, number = self._phase()
            result['own_proposal'] = copy.deepcopy(self.state['proposals'].get(key))
            frozen = (self.state['rounds'][str(self.rounds)]['revisions']
                      if phase in ('synthesizing', 'complete')
                      else self._frozen(number) if phase != 'proposing' else {})
            result['frozen_proposals'] = copy.deepcopy(frozen)
            result['review_history'] = []
            for r in range(1, self.rounds + 1):
                record = self.state['rounds'].get(str(r), {})
                if len(record.get('reviews', {})) == self.slots:
                    result['review_history'].append({'round': r, 'reviews': copy.deepcopy(record['reviews'])})
            result['incoming_issues'] = []
            if phase == 'revising':
                for record in self._round(number)['reviews'].values():
                    if record['target_slot'] == slot:
                        result['incoming_issues'].extend(copy.deepcopy(record['issues']))
            # Only fully revised rounds are shared; an early reviser cannot
            # influence the other agents still working against the same snapshot.
            result['revision_history'] = [
                {'round': r, 'revisions': copy.deepcopy(record['revisions'])}
                for r in range(1, self.rounds + 1)
                if len((record := self.state['rounds'].get(str(r), {})).get('revisions', {})) == self.slots]
            result['syntheses'] = copy.deepcopy(self.state['syntheses'])
            return result

    def propose(self, slot, document, primary_sha):
        with self.lock:
            key = self._slot(slot)
            _candidates(document); _sha(primary_sha)
            payload = {'document': document, 'primary_sha256': primary_sha}
            if key in self.state['proposals']:
                return self._retry(self.state['proposals'][key], payload)
            if self._phase()[0] != 'proposing':
                raise ValueError('Independent proposal phase is closed')
            receipt = self._receipt('propose', slot, payload, primary_sha256=primary_sha)
            self.state['proposals'][key] = {**copy.deepcopy(payload), 'receipt': receipt}
            self._save()
            return copy.deepcopy(receipt)

    def review(self, slot, target_slot, proposal_sha, issues, expected_round=None):
        with self.lock:
            key = self._slot(slot)
            self._slot(target_slot); _sha(proposal_sha)
            payload = {'target_slot': target_slot, 'proposal_sha256': proposal_sha, 'issues': issues}
            phase, number = self._phase()
            if expected_round is not None:
                if type(expected_round) is not int or not 1 <= expected_round <= self.rounds:
                    raise ValueError('Unknown discussion round')
                previous = self.state['rounds'].get(str(expected_round), {}).get('reviews', {}).get(key)
                if previous:
                    return self._retry(previous, payload)
                if expected_round != number:
                    raise ValueError('Review round is stale or not yet open')
            if phase != 'reviewing':
                if expected_round is None:
                    for record in self.state['rounds'].values():
                        previous = record['reviews'].get(key)
                        if previous and previous['receipt']['payload_sha256'] == _digest(payload):
                            return copy.deepcopy(previous['receipt'])
                raise ValueError('Peer reviews require all proposals or preceding revisions to be frozen')
            current = self._round(number)
            if key in current['reviews']:
                return self._retry(current['reviews'][key], payload)
            if target_slot != (slot + 1 + (number - 1) % (self.slots - 1)) % self.slots:
                raise ValueError('Review must address the assigned round-robin peer')
            target = self._frozen(number)[str(target_slot)]
            if proposal_sha != target['primary_sha256']:
                raise ValueError('Peer review must bind to the exact frozen proposal SHA-256')
            candidates = _candidates(target['document'])
            if not isinstance(issues, list):
                raise ValueError('issues must be a list')
            existing = {issue['id'] for record in self.state['rounds'].values()
                        for review in record['reviews'].values() for issue in review['issues']}
            seen = set()
            for issue in issues:
                if not isinstance(issue, dict):
                    raise ValueError('Each peer issue must be an object')
                ident = _text(issue.get('id'), 'Issue id')
                if ident in seen or ident in existing:
                    raise ValueError('Issue IDs must be unique throughout the team discussion')
                seen.add(ident)
                if issue.get('candidate_id') not in candidates:
                    raise ValueError('Peer issue must name a candidate in the frozen target proposal')
                if issue.get('kind') not in ('factual', 'methodological'):
                    raise ValueError('Issue kind must be factual or methodological')
                _text(issue.get('problem'), 'Issue problem')
                _text(issue.get('repair'), 'Issue repair')
                _sources(issue.get('source_ids'))
                if issue['kind'] == 'factual' and not issue['source_ids']:
                    raise ValueError('Factual criticisms require retrieved source IDs')
            receipt = self._receipt('review', slot, payload, round=number,
                                    target_slot=target_slot, proposal_sha256=proposal_sha)
            current['reviews'][key] = {**copy.deepcopy(payload), 'receipt': receipt}
            self._save()
            return copy.deepcopy(receipt)

    def revise(self, slot, document, primary_sha, decisions, expected_round=None):
        with self.lock:
            key = self._slot(slot)
            new_candidates = _candidates(document); _sha(primary_sha)
            payload = {'document': document, 'primary_sha256': primary_sha, 'decisions': decisions}
            phase, number = self._phase()
            if expected_round is not None:
                if type(expected_round) is not int or not 1 <= expected_round <= self.rounds:
                    raise ValueError('Unknown discussion round')
                previous = self.state['rounds'].get(str(expected_round), {}).get('revisions', {}).get(key)
                if previous:
                    return self._retry(previous, payload)
                if expected_round != number:
                    raise ValueError('Revision round is stale or not yet open')
            if phase != 'revising':
                if expected_round is None:
                    for record in self.state['rounds'].values():
                        previous = record['revisions'].get(key)
                        if previous and previous['receipt']['payload_sha256'] == _digest(payload):
                            return copy.deepcopy(previous['receipt'])
                raise ValueError('Revisions require all peers to finish reviews of the frozen round')
            current = self._round(number)
            if key in current['revisions']:
                return self._retry(current['revisions'][key], payload)
            before = _candidates(self._frozen(number)[key]['document'])
            if set(before) != set(new_candidates):
                raise ValueError('Preserve each candidate ID through revisions; retain rejected candidates explicitly')
            incoming = {issue['id']: issue for review in current['reviews'].values()
                        if review['target_slot'] == slot for issue in review['issues']}
            if not isinstance(decisions, list):
                raise ValueError('decisions must be a list')
            seen = set()
            for decision in decisions:
                if not isinstance(decision, dict):
                    raise ValueError('Each decision must be an object')
                ident = decision.get('issue_id')
                if not isinstance(ident, str) or ident not in incoming or ident in seen:
                    raise ValueError('Each incoming issue requires exactly one explicit decision')
                seen.add(ident)
                choice = decision.get('decision')
                if choice not in ('accepted', 'rejected', 'uncertain'):
                    raise ValueError('Decision must be accepted, rejected or uncertain')
                _text(decision.get('reason'), 'Decision reason')
                _sources(decision.get('source_ids'))
                if not isinstance(decision.get('change'), str):
                    raise ValueError('Decision change must explicitly describe the change or lack of change')
                if choice == 'accepted':
                    _text(decision['change'], 'Accepted change')
                    candidate = incoming[ident]['candidate_id']
                    old = _scientific_content(before[candidate])
                    new = _scientific_content(new_candidates[candidate])
                    if _canonical(old) == _canonical(new):
                        raise ValueError('Accepting an issue requires an actual change to its corresponding candidate')
            if seen != set(incoming):
                raise ValueError('Every incoming issue must be addressed exactly once')
            receipt = self._receipt('revise', slot, payload, round=number, primary_sha256=primary_sha)
            current['revisions'][key] = {**copy.deepcopy(payload), 'receipt': receipt}
            self._save()
            return copy.deepcopy(receipt)

    def synthesize(self, slot, document, primary_sha):
        with self.lock:
            self._slot(slot)
            if slot != 0:
                raise ValueError('Only the coordinator may synthesize')
            _sha(primary_sha)
            payload = {'document': document, 'primary_sha256': primary_sha}
            for previous in self.state['syntheses']:
                if previous['primary_sha256'] == primary_sha:
                    return self._retry(previous, payload)
            if self._phase()[0] not in ('synthesizing', 'complete'):
                raise ValueError('Only the coordinator may synthesize after every review and revision round')
            candidates = _candidates(document)
            if len(candidates) < 8:
                raise ValueError('Synthesis must preserve at least eight candidates')
            final = self.state['rounds'][str(self.rounds)]['revisions']
            required = {(int(key), ident, value['primary_sha256'])
                        for key, value in final.items() for ident in _candidates(value['document'])}
            found = set()
            for item in candidates.values():
                origin = item.get('origin')
                if not isinstance(origin, dict) or type(origin.get('slot')) is not int:
                    raise ValueError('Every synthesized candidate requires a final frozen origin')
                ident = (origin['slot'], origin.get('candidate_id'), origin.get('proposal_sha256'))
                if ident not in required or ident in found:
                    raise ValueError('Synthesis origins must match distinct candidates in final frozen proposals')
                found.add(ident)
            if found != required:
                raise ValueError('Synthesis must retain every researcher candidate, including rejected candidates')
            receipt = self._receipt('synthesize', slot, payload, primary_sha256=primary_sha,
                                    version=len(self.state['syntheses']) + 1)
            self.state['syntheses'].append({**copy.deepcopy(payload), 'receipt': receipt})
            self._save()
            return copy.deepcopy(receipt)

    def grade_errors(self, document, primary_sha):
        """Permit grading/export of an exact historical synthesis, including best."""
        with self.lock:
            try:
                _sha(primary_sha)
                for entry in self.state['syntheses']:
                    if entry['primary_sha256'] == primary_sha and _canonical(entry['document']) == _canonical(document):
                        return []
            except (ValueError, TypeError):
                pass
            return ['Primary document must exactly match a recorded completed team synthesis and its SHA-256']

    def summary(self):
        with self.lock:
            phase, number = self._phase()
            reviews = sum(len(x['reviews']) for x in self.state['rounds'].values())
            revisions = sum(len(x['revisions']) for x in self.state['rounds'].values())
            return {'schema_version': self.state['schema_version'], 'slots': self.slots,
                    'rounds': self.rounds, 'phase': phase, 'round': number,
                    'complete': bool(self.state['syntheses']),
                    'registered_agents': len(self.state['roster']),
                    'proposal_count': len(self.state['proposals']), 'review_count': reviews,
                    'revision_count': revisions, 'synthesis_count': len(self.state['syntheses']),
                    'event_count': len(self.state['events']),
                    'scientific_validation': 'not_performed', 'independent_acceptance': False}
