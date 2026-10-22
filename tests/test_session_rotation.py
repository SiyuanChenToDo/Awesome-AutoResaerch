"""Phase-barrier session rotation: board markers, ledger bookkeeping, resume argv."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sage.autonomous.dsh_runtime import (
    FRESH_SESSION_LIMIT,
    RESTART_ESCAPE_FAILURES,
    SESSION_ROTATION_RECEIPT_SCHEMA,
    accept_session_event,
    fresh_restart_ledger,
    load_restart_ledger,
    native_argv,
    plan_restart,
    public_event,
    restart_ledger_path,
    rotate_session,
    save_restart_ledger,
    save_session,
    saved_session,
    session_from_log,
    state_path,
)
from sage.autonomous.lifecycle import resumed_argv, supervise
from sage.autonomous.team import TeamBoard


SESSION_A = 'session-54b62236-a4ad-4f77-881f-217eeac651f2'
SESSION_B = 'session-1e476eda-9b9d-4fd9-95ac-3020381d7148'


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def proposal(slot, count=2):
    return {'candidates': [{'id': f'C{i}', 'title': f'Synthetic slot {slot} candidate {i}',
                            'hypothesis': f'Synthetic testable statement {i}',
                            'source_ids': ['fixture-1', 'fixture-2']}
                           for i in range(count)], 'selected_ids': ['C0']}


def issues(slot, number=1):
    return [{'id': f'R{number}-slot{slot}', 'candidate_id': 'C0', 'kind': 'methodological',
             'problem': 'The synthetic control is underspecified',
             'repair': 'Specify a matched synthetic control',
             'target_fields': ['hypothesis'], 'source_ids': []}]


class TeamRotationMarkerTests(unittest.TestCase):
    """The board advertises one pending rotation per phase barrier and session."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.addCleanup(self.folder.cleanup)
        self.board = TeamBoard(self.root / 'private')
        for slot in range(4):
            self.board.register(slot, f'agent-{slot}', self.root / f'worktree-{slot}',
                                f'session-{slot}')

    def propose_all(self):
        for slot in range(4):
            document = proposal(slot)
            self.board.propose(slot, document, sha(document))

    def test_propose_never_rotates_and_review_barrier_is_advertised(self):
        self.assertNotIn('session_rotation', self.board.snapshot(0))
        self.propose_all()
        snapshot = self.board.snapshot(0)
        self.assertEqual(snapshot['next_action'], 'review')
        self.assertEqual(snapshot['session_rotation'], 'review:r1')
        # The pending marker is re-advertised until the manager consumes it.
        self.assertEqual(self.board.snapshot(0)['session_rotation'], 'review:r1')
        self.board.take_session_rotation(0, 'review:r1')
        self.assertNotIn('session_rotation', self.board.snapshot(0))

    def test_validation_status_reads_do_not_advertise_markers(self):
        self.propose_all()
        self.assertNotIn('session_rotation', self.board.status(0))
        self.assertEqual(self.board.snapshot(0)['session_rotation'], 'review:r1')

    def test_take_requires_the_advertised_barrier_and_is_one_shot(self):
        self.propose_all()
        self.board.snapshot(0)  # issues the pending marker
        with self.assertRaises(ValueError):
            self.board.take_session_rotation(0, 'revise:r1')
        with self.assertRaises(ValueError):
            self.board.take_session_rotation(1)
        self.assertEqual(self.board.take_session_rotation(0), 'review:r1')
        with self.assertRaises(ValueError):
            self.board.take_session_rotation(0)

    def test_revision_and_synthesis_barriers(self):
        self.propose_all()
        self.board.snapshot(0)
        self.board.take_session_rotation(0, 'review:r1')
        for slot in range(4):
            status = self.board.status(slot)
            self.board.review(slot, status['review_target'], status['target_primary_sha256'],
                              issues(slot), expected_round=1)
        self.assertEqual(self.board.snapshot(0)['session_rotation'], 'revise:r1')
        for slot in range(4):
            document = proposal(slot)
            decisions = [{'issue_id': issue['id'], 'decision': 'rejected',
                          'reason': 'Synthetic decision justification', 'source_ids': [],
                          'change': ''}
                         for issue in self.board.snapshot(slot)['incoming_issues']]
            self.board.revise(slot, document, sha(document), decisions, expected_round=1)
        # Round 2 opens the next review barrier only for slots in the new session.
        self.assertEqual(self.board.snapshot(0)['session_rotation'], 'review:r2')

    def test_session_rebind_resets_the_rotation_record(self):
        self.propose_all()
        self.board.snapshot(0)
        self.board.take_session_rotation(0, 'review:r1')
        receipt = self.board.register(0, 'agent-0', self.root / 'worktree-0', 'session-0b')
        self.assertTrue(receipt['session_rebound'])
        self.assertEqual(self.board.state['roster']['0']['session_id'], 'session-0b')
        # The new native session owes its own rotation at the same barrier.
        self.assertEqual(self.board.snapshot(0)['session_rotation'], 'review:r1')
        self.assertEqual(self.board.register(0, 'agent-0', self.root / 'worktree-0',
                                             'session-0b'), receipt)
        with self.assertRaises(ValueError):
            self.board.register(0, 'agent-other', self.root / 'worktree-0', 'session-x')

    def test_synthesize_barrier_only_for_the_coordinator(self):
        self.propose_all()
        for number in (1, 2):
            for slot in range(4):
                status = self.board.status(slot)
                self.board.review(slot, status['review_target'],
                                  status['target_primary_sha256'], [], expected_round=number)
            for slot in range(4):
                document = proposal(slot)
                self.board.revise(slot, document, sha(document), [], expected_round=number)
        self.assertEqual(self.board.snapshot(0)['session_rotation'], 'synthesize')
        finished = self.board.snapshot(1)
        self.assertEqual(finished['next_action'], 'finished')
        self.assertNotIn('session_rotation', finished)


class RotateSessionTests(unittest.TestCase):
    """rotate_session: ledger receipt, pointer deletion, no failure accounting."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.worktree = self.base / 'agent-worktree'
        self.worktree.mkdir()
        self.state_root = self.base / 'manager-private'
        self.agent = 'captain-nemo'

    def failing_ledger(self, failures, session=SESSION_A):
        save_session(self.worktree, self.agent, session, state_root=self.state_root)
        ledger = fresh_restart_ledger(self.worktree, self.agent)
        ledger['current_session_id'] = session
        ledger['consecutive_failures'] = failures
        save_restart_ledger(self.worktree, self.agent, state_root=self.state_root, ledger=ledger)
        return ledger

    def test_rotation_archives_pointer_and_never_touches_failures(self):
        self.failing_ledger(RESTART_ESCAPE_FAILURES - 1)
        result = rotate_session(self.worktree, self.agent, self.state_root,
                                reason='review:r1')
        self.assertEqual(result['archived_session_id'], SESSION_A)
        self.assertEqual(result['rotated_session_count'], 1)
        self.assertFalse(state_path(self.worktree, self.state_root).exists())
        ledger = load_restart_ledger(self.worktree, self.agent, state_root=self.state_root)
        self.assertEqual(ledger['rotated_session_count'], 1)
        self.assertEqual(ledger['consecutive_failures'], RESTART_ESCAPE_FAILURES - 1)
        self.assertIsNone(ledger['current_session_id'])
        rotated = [entry for entry in ledger['history'] if entry.get('event') == 'session_rotated']
        self.assertEqual(len(rotated), 1)
        self.assertEqual(rotated[0]['reason'], 'review:r1')
        self.assertEqual(rotated[0]['archived_session_id'], SESSION_A)
        receipt = json.loads((self.state_root / (self.agent + '.session-rotation.json'))
                             .read_text(encoding='utf-8'))
        self.assertEqual(receipt['schema_version'], SESSION_ROTATION_RECEIPT_SCHEMA)
        self.assertEqual(receipt['reason'], 'review:r1')
        self.assertEqual(receipt['archived_session_id'], SESSION_A)
        self.assertEqual(receipt['rotated_session_count'], 1)
        # The next start() resolves no session: the native argv carries no --session-id.
        plan = plan_restart(self.worktree, self.agent, self.state_root,
                            resume_session_id=None, prompt_source='restart', slot=1)
        self.assertFalse(plan['fresh_reset'])
        self.assertIsNone(plan['resume_session_id'])
        argv = native_argv('/opt/native/dsh', prompt='Continue',
                           resume_session_id=plan['resume_session_id'])
        self.assertNotIn('--session-id', argv)

    def test_rotation_is_not_bounded_by_the_escape_or_terminal_policy(self):
        self.failing_ledger(RESTART_ESCAPE_FAILURES, session=SESSION_B)
        ledger = load_restart_ledger(self.worktree, self.agent, state_root=self.state_root)
        ledger['fresh_session_count'] = FRESH_SESSION_LIMIT
        save_restart_ledger(self.worktree, self.agent, state_root=self.state_root, ledger=ledger)
        # The same counters would raise RuntimeError inside plan_restart; a
        # routine phase rotation must stay independent of that policy.
        result = rotate_session(self.worktree, self.agent, self.state_root,
                                reason='synthesize')
        self.assertEqual(result['rotated_session_count'], 1)
        ledger = load_restart_ledger(self.worktree, self.agent, state_root=self.state_root)
        self.assertEqual(ledger['consecutive_failures'], RESTART_ESCAPE_FAILURES)
        self.assertEqual(ledger['fresh_session_count'], FRESH_SESSION_LIMIT)

    def test_plan_restart_never_resurrects_a_rotated_session(self):
        self.failing_ledger(0)
        rotate_session(self.worktree, self.agent, self.state_root, reason='review:r1')
        plan = plan_restart(self.worktree, self.agent, self.state_root,
                            resume_session_id=SESSION_A, prompt_source='restart')
        self.assertFalse(plan['fresh_reset'])
        self.assertTrue(plan['rotation_reset'])
        self.assertIsNone(plan['resume_session_id'])
        argv = native_argv('/opt/native/dsh', prompt='x', resume_session_id=plan['resume_session_id'])
        self.assertNotIn('--session-id', argv)

    def test_rotation_without_any_recorded_session_is_still_recorded(self):
        result = rotate_session(self.worktree, self.agent, self.state_root,
                                reason='review:r1')
        self.assertIsNone(result['archived_session_id'])
        ledger = load_restart_ledger(self.worktree, self.agent, state_root=self.state_root)
        self.assertEqual(ledger['rotated_session_count'], 1)
        self.assertEqual(ledger['history'][-1]['event'], 'session_rotated')

    def test_saved_pointer_survives_only_for_the_rotated_agent(self):
        save_session(self.worktree, self.agent, SESSION_A, state_root=self.state_root)
        other = self.base / 'other-worktree'
        other.mkdir()
        save_session(other, 'agent-other', SESSION_B, state_root=self.state_root)
        rotate_session(self.worktree, self.agent, self.state_root, reason='review:r1')
        self.assertIsNone(saved_session(self.worktree, self.agent, state_root=self.state_root))
        self.assertEqual(saved_session(other, 'agent-other', state_root=self.state_root), SESSION_B)


class RuntimeRotationBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.worktree = self.base / 'worker'
        self.worktree.mkdir()
        self.root = self.base / 'private'
        self.agent = 'fixture-worker'
        self.count = 0
        self.previous = None
        self.events = []
        self.register = mock.patch('sage.autonomous.dsh_runtime.register_researcher').start()
        self.addCleanup(mock.patch.stopall)

    def accept(self, session, *, cwd=None, slot=1, initial=None):
        event = {'type': 'session', 'sessionId': session, 'cwd': str(cwd or self.worktree)}
        self.count, transition = accept_session_event(event, worktree=self.worktree,
            agent_id=self.agent, state_root=self.root, previous=self.previous,
            initial_resume=initial, rotation_count=self.count, slot=slot)
        if transition:
            self.events.append(transition)
        self.events.append(event)
        self.previous = session

    def rotate(self):
        return rotate_session(self.worktree, self.agent, self.root, reason='review:r1')

    def test_authorized_rotation_rebinds_roster_pointer_and_log_resume_identity(self):
        self.accept(SESSION_A, initial=SESSION_A)
        self.rotate()
        self.accept(SESSION_B, initial=SESSION_A)
        self.accept(SESSION_B, initial=SESSION_A)
        self.assertEqual(self.register.call_args_list, [
            mock.call(1, self.agent, self.worktree, SESSION_A),
            mock.call(1, self.agent, self.worktree, SESSION_B)])
        self.assertEqual(saved_session(self.worktree, self.agent, state_root=self.root), SESSION_B)
        log = self.base / 'worker.log'
        log.write_text('\n'.join(map(json.dumps, self.events)), encoding='utf-8')
        self.assertEqual(session_from_log(log), SESSION_B)
        plan = plan_restart(self.worktree, self.agent, self.root,
                            resume_session_id=session_from_log(log), prompt_source='restart')
        self.assertEqual(plan['resume_session_id'], SESSION_B)
        self.assertFalse(plan['fresh_reset'])

    def test_unapproved_change_or_initial_resume_mismatch_remains_rejected(self):
        with self.assertRaises(ValueError):
            self.accept(SESSION_B, initial=SESSION_A)
        self.accept(SESSION_A)
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.accept(SESSION_B)
        self.assertEqual(saved_session(self.worktree, self.agent, state_root=self.root), SESSION_A)

    def test_receipt_cannot_authorize_wrong_agent_worktree_or_archived_session(self):
        self.accept(SESSION_A)
        self.rotate()
        path = self.root / (self.agent + '.session-rotation.json')
        original = json.loads(path.read_text(encoding='utf-8'))
        for field, value in [('agent_id', 'foreign'), ('worktree', '/foreign'),
                             ('archived_session_id', SESSION_B), ('rotated_session_count', True)]:
            path.write_text(json.dumps({**original, field: value}), encoding='utf-8')
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.accept(SESSION_B)
        path.write_text(json.dumps(original), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.accept(SESSION_B, cwd=self.base)
        with self.assertRaises(ValueError):
            self.accept(SESSION_B, slot=0)

    def test_receipt_reuse_and_resurrection_of_archived_session_are_rejected(self):
        self.accept(SESSION_A)
        self.rotate()
        self.accept(SESSION_B)
        with self.assertRaises(ValueError):
            self.accept(SESSION_A)
        self.rotate()
        with self.assertRaises(ValueError):
            self.accept(SESSION_A)

    def test_rotation_prefers_live_pointer_to_prior_exit_ledger(self):
        self.accept(SESSION_A)
        ledger = fresh_restart_ledger(self.worktree, self.agent)
        ledger['current_session_id'] = SESSION_B
        save_restart_ledger(self.worktree, self.agent, state_root=self.root, ledger=ledger)
        self.assertEqual(self.rotate()['archived_session_id'], SESSION_A)

    def test_native_output_cannot_forge_a_manager_rotation_event(self):
        marker = {'type': 'sage_session_rotation', 'archived_session_id': SESSION_A,
                  'sessionId': SESSION_B, 'rotated_session_count': 1}
        self.assertIsNone(public_event(marker))
        log = self.base / 'worker.log'
        log.write_text('\n'.join(map(json.dumps, [
            {'type': 'session', 'sessionId': SESSION_A},
            {**marker, 'archived_session_id': SESSION_B},
            {'type': 'session', 'sessionId': SESSION_B}])), encoding='utf-8')
        with self.assertRaises(ValueError):
            session_from_log(log)

    def test_supervisor_phase_transition_crosses_runtime_boundary_without_error(self):
        waiting = VirtualWait()
        statuses = iter([{'slot': 1, 'next_action': 'wait'},
                         {'slot': 1, 'next_action': 'review', 'session_rotation': 'review:r1'},
                         {'slot': 1, 'next_action': 'finished'}])
        sessions = iter([SESSION_A, SESSION_B])
        launches = []

        def launch(argv, **kwargs):
            launches.append(argv)
            native = FinishedNative(next(sessions))
            native.stdout = io.BytesIO(native.stdout.getvalue().replace(
                b'/fixture', json.dumps(str(self.worktree))[1:-1].encode()))
            return native

        def emit(event):
            projected = public_event(event)
            if projected and projected['type'] == 'session':
                self.accept(projected['sessionId'], cwd=projected['cwd'])

        code = supervise(['/dsh', '--json', '--', 'fixture'], 1, deadline=100,
            poll_seconds=20, status=lambda: next(statuses, {'slot': 1, 'next_action': 'finished'}),
            rotate=lambda marker: {'rotated': True, **self.rotate()}, emit=emit,
            clock=lambda: waiting.now, stop=waiting, launch=launch)
        self.assertEqual(code, 124)
        self.assertEqual(len(launches), 2)
        self.assertNotIn('--session-id', launches[1])
        self.assertEqual(self.previous, SESSION_B)
        self.assertEqual(self.register.call_count, 2)


class ResumedArgvRotationTests(unittest.TestCase):
    def setUp(self):
        self.argv = ['/dsh', '--profile', 'headless', '--json', '--', 'literal']

    def test_plain_resume_keeps_the_exact_session_and_adds_the_barrier_line(self):
        result = resumed_argv(self.argv, SESSION_A, 1)
        self.assertIn('--session-id', result)
        self.assertEqual(result[result.index('--session-id') + 1], SESSION_A)
        prompt = result[-1]
        self.assertIn('Barrier checkpoint: ensure your latest findings are saved to '
                      'your wiki or shared notes before polling again.', prompt)
        self.assertNotIn('[rotate-session]', prompt)

    def test_rotated_resume_drops_session_id_and_injects_the_marker(self):
        rotation = {'rotated': True, 'reason': 'review:r1',
                    'archived_session_id': SESSION_A, 'rotated_session_count': 1}
        result = resumed_argv(self.argv, SESSION_A, 2, rotation=rotation)
        self.assertNotIn('--session-id', result)
        self.assertEqual(result[:result.index('--json') + 1],
                         self.argv[:self.argv.index('--json') + 1])
        prompt = result[-1]
        self.assertIn('[rotate-session]', prompt)
        self.assertIn("'review:r1'", prompt)
        self.assertIn(SESSION_A, prompt)
        self.assertIn('workspace files are intact', prompt)
        self.assertIn('rotation #1', prompt)
        # The slot instruction and the barrier checkpoint survive the rotation.
        self.assertIn('Your authenticated research team slot is 2.', prompt)
        self.assertIn('Barrier checkpoint:', prompt)


class VirtualWait:
    def __init__(self):
        self.now = 0
        self.cancelled = False

    def is_set(self):
        return self.cancelled

    def wait(self, timeout):
        self.now += timeout
        return self.cancelled


class FinishedNative:
    def __init__(self, session=SESSION_A, *, final=True, code=0):
        events = [{'type': 'session', 'sessionId': session, 'cwd': '/fixture'}]
        if final:
            events.append({'type': 'final', 'text': 'done'})
        self.stdout = io.BytesIO(('\n'.join(json.dumps(event) for event in events)).encode())
        self.returncode = code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class SuperviseRotationTests(unittest.TestCase):
    def run_native(self, statuses, *, rotate, natives=None):
        waiting = VirtualWait()
        emitted, launches = [], []
        statuses = iter(statuses)
        natives = iter(natives or [FinishedNative(), FinishedNative()])

        def launch(argv, **kwargs):
            launches.append(argv)
            return next(natives)

        def status():
            try:
                value = next(statuses)
            except StopIteration:
                value = {'slot': 1, 'next_action': 'finished'}
            if isinstance(value, Exception):
                raise value
            return value

        code = supervise(['/dsh', '--json', '--', 'literal'], 1, deadline=100,
                         poll_seconds=20, status=status, emit=emitted.append,
                         stop=waiting, clock=lambda: waiting.now, launch=launch,
                         rotate=rotate)
        return code, emitted, launches

    def test_barrier_marker_rotates_and_the_fresh_launch_carries_no_session_id(self):
        calls = []

        def rotate(marker):
            calls.append(marker)
            return {'rotated': True, 'reason': marker,
                    'archived_session_id': SESSION_A, 'rotated_session_count': 1}

        code, events, launches = self.run_native([
            {'slot': 1, 'next_action': 'wait'},
            {'slot': 1, 'next_action': 'review', 'session_rotation': 'review:r1'},
            {'slot': 1, 'next_action': 'finished'}],
            rotate=rotate, natives=[FinishedNative(), FinishedNative(session=SESSION_B)])
        self.assertEqual(code, 124)
        self.assertEqual(calls, ['review:r1'])
        self.assertEqual(len(launches), 2)
        self.assertEqual(launches[0], ['/dsh', '--json', '--', 'literal'])
        self.assertNotIn('--session-id', launches[1])
        self.assertIn('[rotate-session]', launches[1][-1])
        self.assertEqual(sum(x.get('state') == 'resuming' for x in events), 1)

    def test_refused_rotation_falls_back_to_the_exact_session_resume(self):
        def rotate(marker):
            raise ValueError('No pending session rotation for this slot')

        code, events, launches = self.run_native([
            {'slot': 1, 'next_action': 'wait'},
            {'slot': 1, 'next_action': 'review', 'session_rotation': 'review:r1'},
            {'slot': 1, 'next_action': 'finished'}], rotate=rotate)
        self.assertEqual(code, 124)
        self.assertEqual(len(launches), 2)
        self.assertIn('--session-id', launches[1])
        self.assertEqual(launches[1][launches[1].index('--session-id') + 1], SESSION_A)
        self.assertNotIn('[rotate-session]', launches[1][-1])


if __name__ == '__main__':
    unittest.main()
