"""No-network owner-loss regressions, with Linux-only real SIGKILL fixtures."""
from contextlib import ExitStack
from enum import IntEnum
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from sage.autonomous import lifecycle


def identity(pid, *, parent=1, group=None, uid=0, ticks=10, state='S'):
    return {'pid': pid, 'ppid': parent, 'pgid': group or pid, 'sid': group or pid,
            'start_ticks': ticks, 'uid': uid, 'state': state}


def mock_linux_signal_on_windows(test):
    if not hasattr(signal, 'SIGKILL'):
        class FixtureSignals(IntEnum):
            SIGKILL = 9
        patcher = mock.patch.object(signal, 'SIGKILL', FixtureSignals.SIGKILL, create=True)
        patcher.start()
        test.addCleanup(patcher.stop)


class OwnerGuardTests(unittest.TestCase):
    def setUp(self):
        mock_linux_signal_on_windows(self)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = identity(1001)
        self.manager = identity(2002, parent=1001)
        self.guard = lifecycle.NativeOwnerGuard(self.root, self.owner, self.manager, 3003)

    def test_identity_missing_reused_zombie_and_unreadable_are_distinct(self):
        cases = [(FileNotFoundError(), 'owner_missing'),
                 (identity(1001, ticks=11), 'owner_reused'),
                 (identity(1001, uid=1), 'owner_reused'),
                 (identity(1001, state='Z'), 'owner_zombie'),
                 (PermissionError('private path'), 'owner_unverifiable'),
                 (identity(1001), 'alive')]
        for value, expected in cases:
            with self.subTest(expected=expected), mock.patch.object(lifecycle, 'process_identity',
                    side_effect=value if isinstance(value, Exception) else None, return_value=value):
                self.assertEqual(self.guard.owner_status(), expected)

    def test_failure_permanently_closes_admission_even_if_pid_returns(self):
        with mock.patch.object(self.guard, 'owner_status', side_effect=['owner_missing', 'alive']):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'refusing new model work'):
                    self.guard.check()
        self.assertEqual(self.guard.reason, 'owner_missing')

    def test_absent_owner_refuses_spawn(self):
        with mock.patch.object(self.guard, 'owner_status', return_value='owner_missing'), \
                mock.patch.object(lifecycle.subprocess, 'Popen') as spawn:
            with self.assertRaises(ValueError):
                self.guard.launch(['fixture'])
        spawn.assert_not_called()

    def test_loss_during_spawn_keeps_identity_then_stops_returned_process(self):
        child = mock.Mock(pid=4004)
        child.poll.return_value = None
        native = identity(4004, parent=2002, uid=3003)
        with mock.patch.object(self.guard, 'owner_status', side_effect=['alive', 'owner_missing']), \
                mock.patch.object(lifecycle.subprocess, 'Popen', return_value=child), \
                mock.patch.object(lifecycle, 'process_identity', return_value=native), \
                mock.patch.object(lifecycle.os, 'killpg', create=True) as kill:
            with self.assertRaises(ValueError):
                self.guard.launch(['fixture'], start_new_session=True)
        self.assertEqual(self.guard.known[4004]['start_ticks'], 10)
        self.assertEqual(self.guard.reason, 'owner_missing')
        kill.assert_called_once_with(4004, signal.SIGKILL)
        child.wait.assert_called_once_with(timeout=5)
        child.stdout.close.assert_called_once()

    def test_unreadable_child_identity_is_terminal_and_direct_handle_is_reaped(self):
        child = mock.Mock(pid=4004)
        child.poll.return_value = None
        with mock.patch.object(self.guard, 'owner_status', return_value='alive'), \
                mock.patch.object(lifecycle.subprocess, 'Popen', return_value=child), \
                mock.patch.object(lifecycle, 'process_identity', side_effect=PermissionError), \
                mock.patch.object(lifecycle.os, 'killpg', create=True):
            with self.assertRaises(PermissionError):
                self.guard.launch(['fixture'], start_new_session=True)
        self.assertEqual(self.guard.reason, 'native_identity_unverifiable')
        child.wait.assert_called_once_with(timeout=5)

    def test_spawn_registration_is_inside_same_gate_used_for_shutdown(self):
        entered, release, closing = threading.Event(), threading.Event(), threading.Event()
        child = mock.Mock(pid=4004)
        native = identity(4004, parent=2002, uid=3003)
        def spawn(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return child
        def close():
            with self.guard.lock:
                self.guard._close('owner_missing')
                self.assertIn(4004, self.guard.known)
                closing.set()
        with mock.patch.object(self.guard, 'owner_status', return_value='alive'), \
                mock.patch.object(lifecycle.subprocess, 'Popen', side_effect=spawn), \
                mock.patch.object(lifecycle, 'process_identity', return_value=native):
            starter = threading.Thread(target=lambda: self.guard.launch(['fixture']))
            starter.start()
            self.assertTrue(entered.wait(3))
            closer = threading.Thread(target=close)
            closer.start()
            self.assertFalse(closing.wait(0.05))
            release.set()
            starter.join(3); closer.join(3)
        self.assertTrue(closing.is_set())

    def test_multiple_slot_spawns_are_serialized_and_all_identities_retained(self):
        children = [mock.Mock(pid=4000 + x) for x in range(4)]
        with mock.patch.object(self.guard, 'owner_status', return_value='alive'), \
                mock.patch.object(lifecycle.subprocess, 'Popen', side_effect=children), \
                mock.patch.object(lifecycle, 'process_identity', side_effect=lambda pid:
                                  identity(pid, parent=2002, uid=3003)):
            threads = [threading.Thread(target=lambda: self.guard.launch(['fixture'])) for _ in range(4)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(3)
        self.assertEqual(set(self.guard.known), {2002, 4000, 4001, 4002, 4003})

    def run_failure(self, reason='owner_missing', *, cleanup_error=False, write_error=False):
        actions = []
        self.guard.reason = reason
        cleanup = {'verified_no_active_tracked_dependents': True,
                   'verified_no_active_tracked_processes': False, 'remaining': {'active': []}}
        def stop(*args, **kwargs):
            intent = json.loads((self.root / 'runtime-crash.json').read_text()) if not write_error else None
            if intent: self.assertEqual(intent['phase'], 'stopping')
            actions.append('cleanup')
            self.assertTrue(kwargs['keep_current_manager'])
            if cleanup_error: raise OSError('PRIVATE-EXTERNAL-ERROR')
            return cleanup
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(lifecycle, 'stop_tracked_processes', side_effect=stop))
            kill = stack.enter_context(mock.patch.object(lifecycle.os, 'kill', side_effect=lambda *args: actions.append('manager_signal')))
            stack.enter_context(mock.patch.object(lifecycle.time, 'sleep', return_value=None))
            exit_process = stack.enter_context(mock.patch.object(lifecycle.os, '_exit', side_effect=lambda *args: actions.append('force_exit')))
            if write_error:
                stack.enter_context(mock.patch.object(lifecycle, 'atomic_json', side_effect=OSError('PRIVATE-EXTERNAL-ERROR')))
            self.guard._watch()
        kill.assert_called_once_with(2002, signal.SIGTERM)
        exit_process.assert_called_once_with(1)
        self.assertEqual(actions, ['cleanup', 'manager_signal', 'force_exit'])
        return cleanup

    def test_crash_receipt_is_truthful_and_does_not_invent_zero_grades(self):
        self.run_failure()
        receipt = json.loads((self.root / 'runtime-crash.json').read_text())
        self.assertEqual(receipt['schema_version'], 'sage.native_owner_failure.v1')
        self.assertEqual(receipt['launcher_exit_cause'], 'unknown')
        self.assertTrue(receipt['manager_self_exit_requested'])
        self.assertFalse(receipt['manager_exit_observed'])
        result = json.loads((self.root / 'result.json').read_text())
        self.assertEqual(result['workflow_status'], 'incomplete')
        for field in ('scientific_score', 'graded_attempts', 'formal_attempts_used'):
            self.assertIsNone(result[field])
        self.assertFalse(result['shutdown']['cleanup_complete'])

    def test_unverifiable_owner_does_not_compete_for_result(self):
        self.run_failure('owner_unverifiable')
        self.assertTrue((self.root / 'runtime-crash.json').is_file())
        self.assertFalse((self.root / 'result.json').exists())

    def test_existing_terminal_is_never_overwritten(self):
        result = self.root / 'result.json'
        result.write_bytes(b'EXISTING-TERMINAL-BYTES')
        self.run_failure()
        self.assertEqual(result.read_bytes(), b'EXISTING-TERMINAL-BYTES')

    def test_cleanup_failure_still_requests_exit_and_never_claims_clean(self):
        self.run_failure(cleanup_error=True)
        raw = (self.root / 'runtime-crash.json').read_text()
        self.assertNotIn('PRIVATE-EXTERNAL-ERROR', raw)
        self.assertFalse(json.loads(raw)['cleanup']['verified_no_active_tracked_dependents'])

    def test_crash_receipt_write_failure_does_not_skip_cleanup_or_exit(self):
        self.run_failure(write_error=True)
        self.assertTrue((self.root / 'result.json').is_file())

    def test_temporary_receipt_unlink_error_cannot_skip_manager_exit(self):
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path.name.startswith('.crash-result-'):
                raise PermissionError('fixture')
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'unlink', unlink):
            self.run_failure()


class OwnerContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manager_pid = os.getpid()
        self.owner = identity(1001)
        self.metadata = self.root / 'launch.json'
        self.metadata.write_text(json.dumps({'launcher_identity': self.owner, 'agent_uid': 3003}))
        self.env = {'SAGE_RUN_ROOT': str(self.root), 'SAGE_LAUNCHER_PID': '1001',
                    'SAGE_LAUNCHER_START_TICKS': '10'}
        self.addCleanup(lifecycle._OWNER_GUARDS.clear)

    def stack(self, extra_roots=()):
        stack = ExitStack()
        self.addCleanup(stack.close)
        original = Path.stat
        roots = {self.root, *extra_roots}
        metadata = {root / 'launch.json' for root in roots}
        def file_stat(path, **kwargs):
            result = original(path, **kwargs)
            if path in roots | metadata:
                return SimpleNamespace(st_uid=0, st_size=result.st_size,
                    st_mode=(stat.S_IFDIR | 0o755) if path in roots else (stat.S_IFREG | 0o600))
            return result
        stack.enter_context(mock.patch.object(Path, 'stat', file_stat))
        stack.enter_context(mock.patch.object(lifecycle.os, 'geteuid', return_value=0, create=True))
        stack.enter_context(mock.patch.object(lifecycle, 'process_identity', side_effect=lambda pid:
            identity(self.manager_pid, parent=1001) if pid == self.manager_pid else self.owner))
        starter = stack.enter_context(mock.patch.object(lifecycle.NativeOwnerGuard, 'start', autospec=True,
                                                       side_effect=lambda guard: guard))
        return stack, starter

    def test_four_runtime_instances_acquire_one_process_shared_guard(self):
        _, start = self.stack()
        guards = []
        threads = [threading.Thread(target=lambda: guards.append(
            lifecycle.acquire_owner_guard(self.root, 3003, environ=self.env))) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(3)
        self.assertEqual(len(guards), 4)
        self.assertEqual(len({id(value) for value in guards}), 1)
        start.assert_called_once()

    def test_second_run_root_cannot_create_another_guard_in_same_manager(self):
        alternate = self.root / 'other-run'
        alternate.mkdir()
        (alternate / 'launch.json').write_bytes(self.metadata.read_bytes())
        _, start = self.stack(extra_roots=(alternate,))
        guard = lifecycle.acquire_owner_guard(self.root, 3003, environ=self.env)
        with self.assertRaisesRegex(ValueError, 'changed within one manager'):
            lifecycle.acquire_owner_guard(alternate, 3003,
                environ=dict(self.env, SAGE_RUN_ROOT=str(alternate)))
        self.assertEqual(guard.destination, self.root)
        self.assertEqual(len(lifecycle._OWNER_GUARDS), 1)
        start.assert_called_once()

    def test_missing_mismatched_or_changed_contract_is_rejected(self):
        _, start = self.stack()
        for field, value in [('SAGE_LAUNCHER_PID', '9999'), ('SAGE_LAUNCHER_START_TICKS', '11'),
                             ('SAGE_RUN_ROOT', str(self.root / 'other'))]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                lifecycle.acquire_owner_guard(self.root, 3003, environ=dict(self.env, **{field: value}))
        with self.assertRaises(ValueError):
            lifecycle.acquire_owner_guard(self.root, 9999, environ=self.env)
        start.assert_not_called()

    def test_boolean_or_partial_identity_is_not_accepted_as_pid_metadata(self):
        self.stack()
        for owner in ({'pid': 1001}, dict(self.owner, uid=False)):
            self.metadata.write_text(json.dumps({'launcher_identity': owner, 'agent_uid': 3003}))
            with self.assertRaises(ValueError):
                lifecycle.acquire_owner_guard(self.root, 3003, environ=self.env)


class ManagerCleanupTests(unittest.TestCase):
    def setUp(self):
        mock_linux_signal_on_windows(self)

    def test_current_manager_excluded_but_same_group_grader_is_signaled(self):
        manager = identity(os.getpid())
        grader = identity(3001, parent=manager['pid'], group=manager['pgid'])
        agent = identity(4001, parent=manager['pid'], uid=3003)
        known = {x['pid']: x for x in (manager, grader, agent)}
        calls = 0
        def scan(*args):
            nonlocal calls
            calls += 1
            return {'active': [manager, grader, agent] if calls == 1 else [manager],
                    'zombies': [], 'unreadable': [], 'unscoped_agent_pids': [9999]}
        with mock.patch.object(lifecycle, 'track_native_processes', side_effect=scan), \
                mock.patch.object(lifecycle, 'process_identity', side_effect=lambda pid: known[pid]), \
                mock.patch.object(lifecycle.os, 'getpgrp', return_value=manager['pid'], create=True), \
                mock.patch.object(lifecycle.os, 'kill') as kill, \
                mock.patch.object(lifecycle.os, 'killpg', create=True) as killpg:
            result = lifecycle.stop_tracked_processes(manager['pid'], '.', known, 3003,
                term_seconds=0, kill_seconds=0, keep_current_manager=True)
        kill.assert_called_once_with(grader['pid'], signal.SIGTERM)
        killpg.assert_called_once_with(agent['pid'], signal.SIGTERM)
        self.assertTrue(result['verified_no_active_tracked_dependents'])
        self.assertFalse(result['verified_no_active_tracked_processes'])

    def test_changed_identity_between_scan_and_signal_is_never_killed(self):
        manager = identity(os.getpid())
        agent = identity(4001, parent=manager['pid'], uid=3003)
        known = {x['pid']: x for x in (manager, agent)}
        snapshot = {'active': [manager, agent], 'unreadable': [], 'zombies': []}
        with mock.patch.object(lifecycle, 'track_native_processes', side_effect=lambda *args: dict(snapshot)), \
                mock.patch.object(lifecycle, 'process_identity', return_value=dict(agent, start_ticks=99)), \
                mock.patch.object(lifecycle.os, 'getpgrp', return_value=manager['pid'], create=True), \
                mock.patch.object(lifecycle.os, 'kill') as kill, \
                mock.patch.object(lifecycle.os, 'killpg', create=True) as killpg:
            result = lifecycle.stop_tracked_processes(manager['pid'], '.', known, 3003,
                term_seconds=0, kill_seconds=0, keep_current_manager=True)
        kill.assert_not_called(); killpg.assert_not_called()
        self.assertFalse(result['verified_no_active_tracked_dependents'])


_LINUX_FIXTURE = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
from unittest.mock import patch
from sage.artifacts import atomic_json
from sage.autonomous import lifecycle
root=Path(sys.argv[2]); mode=sys.argv[3]; role=sys.argv[1]
script=str(Path(__file__).resolve())
def save(name, data): atomic_json(root/name, data)
if role=='launcher':
    owner=lifecycle.process_identity(os.getpid())
    save('launch.json', {'launcher_identity':owner,'agent_uid':os.getuid()})
    env=dict(os.environ,SAGE_LAUNCHER_PID=str(os.getpid()),
        SAGE_LAUNCHER_START_TICKS=str(owner['start_ticks']),SAGE_RUN_ROOT=str(root))
    manager=subprocess.Popen([sys.executable,script,'manager',str(root),mode],env=env,
        start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    save('manager.json', lifecycle.process_identity(manager.pid))
    while True: time.sleep(.05)
elif role=='manager':
    # Force the bounded fallback to be exercised; no upstream/model is needed.
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    guard=lifecycle.acquire_owner_guard(root,os.getuid())
    guard.poll_seconds=.05;guard.manager_exit_grace=.3
    if mode=='race':
        original=subprocess.Popen
        def pause_spawn(*args,**kwargs):
            child=original(*args,**kwargs)
            save('race.json',lifecycle.process_identity(child.pid))
            end=time.monotonic()+10
            while not (root/'release').exists() and time.monotonic()<end: time.sleep(.01)
            return child
        with patch.object(lifecycle.subprocess,'Popen',side_effect=pause_spawn):
            try:
                guard.launch([sys.executable,script,'worker',str(root),mode,'0'],
                    start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except ValueError:
                save('restart-refused.json',{'closed':True})
    else:
        children=[]
        for slot in range(4):
            child,record=guard.launch([sys.executable,script,'worker',str(root),mode,str(slot)],
                start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            children.append(record)
        grader=subprocess.Popen([sys.executable,script,'grader',str(root),mode],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        children.append(lifecycle.process_identity(grader.pid))
        end=time.monotonic()+10
        while not (root/'detached.json').exists() and time.monotonic()<end:time.sleep(.01)
        children.append(json.loads((root/'detached.json').read_text()))
        with guard.lock:lifecycle.track_native_processes(os.getpid(),root,guard.known,os.getuid())
        save('ready.json',children)
    while True:
        if guard.reason:
            try:
                guard.launch([sys.executable,script,'worker',str(root),mode,'forbidden'],
                    start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except ValueError:save('restart-refused.json',{'closed':True})
        time.sleep(.05)
elif role=='worker':
    slot=sys.argv[4]
    if mode!='race' and slot=='0':
        child=subprocess.Popen([sys.executable,script,'detached',str(root),mode],
            start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        save('detached.json',lifecycle.process_identity(child.pid))
    while True:
        with (root/('work-'+slot)).open('a') as stream:stream.write('.')
        time.sleep(.05)
else:
    if role=='detached':signal.signal(signal.SIGTERM,signal.SIG_IGN)
    while True:time.sleep(.05)
'''


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux real parent SIGKILL and process identities')
class RealOwnerLossTests(unittest.TestCase):
    def wait_for(self, condition, seconds=25):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = condition()
            if value: return value
            time.sleep(.02)
        self.fail('Offline process fixture exceeded its bounded wait')

    def active(self, record):
        try:
            current = lifecycle.process_identity(record['pid'])
            return current['start_ticks'] == record['start_ticks'] and current['state'] != 'Z'
        except FileNotFoundError:
            return False

    def run_loss(self, mode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'fixture.py'
            script.write_text(_LINUX_FIXTURE, encoding='utf-8')
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
            launcher = subprocess.Popen([sys.executable, str(script), 'launcher', str(root), mode],
                env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'],
                                          start_new_session=True)
            records = [lifecycle.process_identity(launcher.pid)]
            try:
                self.wait_for(lambda: (root / 'manager.json').exists(), seconds=10)
                manager = json.loads((root / 'manager.json').read_text())
                records.append(manager)
                marker = root / ('race.json' if mode == 'race' else 'ready.json')
                self.wait_for(marker.exists, seconds=15)
                children = json.loads(marker.read_text())
                children = [children] if mode == 'race' else children
                records.extend(children)
                started = time.monotonic()
                os.kill(launcher.pid, signal.SIGKILL)
                launcher.wait(timeout=5)
                self.assertEqual(launcher.returncode, -signal.SIGKILL)
                if mode == 'race': (root / 'release').write_text('release fixture spawn')
                self.wait_for(lambda: (root / 'result.json').exists())
                self.wait_for(lambda: not any(self.active(x) for x in records[1:]))
                self.assertLess(time.monotonic() - started, 25)
                self.assertIsNone(unrelated.poll(), 'Never kill an unrelated process using the same UID')
                self.assertTrue((root / 'restart-refused.json').exists())
                self.assertFalse((root / 'work-forbidden').exists())
                receipt = json.loads((root / 'runtime-crash.json').read_text())
                # The guard can observe SIGKILL before this parent reaps the PID.
                # Both states mean the same verified owner has stopped; cleanup
                # and unrelated-process assertions below remain mandatory.
                self.assertIn(receipt['reason'], {'owner_missing', 'owner_zombie'})
                self.assertEqual(receipt['launcher_exit_cause'], 'unknown')
                self.assertTrue(receipt['cleanup']['verified_no_active_tracked_dependents'], receipt)
                self.assertFalse(receipt['manager_exit_observed'])
                self.assertTrue(receipt['manager_self_exit_requested'])
                self.assertEqual(json.loads((root / 'result.json').read_text())['workflow_status'], 'incomplete')
                if mode != 'race':
                    self.assertTrue(any(x['signal'] == 'SIGKILL' and x['pgid'] == children[-1]['pgid']
                                        for x in receipt['cleanup']['signals']))
                    self.assertTrue(any(x['target_kind'] == 'pid' and x['witness_pid'] == children[-2]['pid']
                                        for x in receipt['cleanup']['signals']))
            finally:
                for record in records:
                    if self.active(record):
                        try:
                            os.killpg(record['pgid'], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                if unrelated.poll() is None: unrelated.kill()
                unrelated.wait(timeout=5)
                if launcher.poll() is None: launcher.kill()
                launcher.wait(timeout=5)

    def test_parent_sigkill_stops_all_slots_detached_tool_and_same_group_grader(self):
        self.run_loss('running')

    def test_parent_sigkill_during_spawn_cannot_leave_an_unregistered_native_process(self):
        self.run_loss('race')


if __name__ == '__main__':
    unittest.main()
