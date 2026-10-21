"""Offline shutdown contracts; no native runtime installation or paid calls."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from sage.autonomous import lifecycle, runner
from sage.checkpoints import Checkpoint
from sage.config import RunConfig
from sage.errors import ConfigurationError
from sage.providers import OpenAIConfig
from sage.runtime import Runtime


class RuntimeCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_is_terminal_but_remote_outcome_and_checkpoint_remain_uncertain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkpoint = Checkpoint(root / 'checkpoint.json', {'offline': True})
            runtime = Runtime(None, None, None, RunConfig(), checkpoint=checkpoint)
            entered, finalized = asyncio.Event(), asyncio.Event()
            async def request():
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finalized.set()
            task = asyncio.create_task(runtime.call('model', 'fixture.read', request,
                output_tokens=17, cache_input={'paper': 'fixture'}))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(finalized.is_set())
            self.assertEqual([e['status'] for e in runtime.audit], ['started', 'cancelled'])
            self.assertEqual(runtime.audit[-1]['remote_outcome'], 'unknown')
            self.assertEqual(runtime.usage['model_calls'], 1)
            self.assertEqual(runtime.usage['reserved_output_tokens'], 17)
            stored = next(iter(checkpoint.entries.values()))
            self.assertEqual(stored['status'], 'pending')
            self.assertTrue(stored['cancellation_requested'])
            resumed = Checkpoint(root / 'resumed.json', {'offline': True}, resume=checkpoint.path)
            resumed_runtime = Runtime(None, None, None, RunConfig(), checkpoint=resumed)
            with self.assertRaisesRegex(ConfigurationError, 'ambiguous'):
                await resumed_runtime.call('model', 'fixture.read', request,
                    output_tokens=17, cache_input={'paper': 'fixture'})
            self.assertEqual(resumed_runtime.usage['model_calls'], 1)


class NativeIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.known = {}

    def process(self, pid, parent=1, group=None, sid=None, uid=0, ticks=10, state='S'):
        path = self.proc / str(pid)
        path.mkdir(exist_ok=True)
        fields = [state, str(parent), str(group or pid), str(sid or group or pid)] + ['0'] * 15 + [str(ticks)]
        (path / 'stat').write_text(f'{pid} (name with ) parens) ' + ' '.join(fields))
        (path / 'status').write_text(f'Name:\tfixture\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n')
        return lifecycle.process_identity(pid, self.proc)

    def scan(self):
        return lifecycle.track_native_processes(101, self.root, self.known, 2000, proc_root=self.proc)

    def test_retains_separate_child_group_after_parent_exit_without_reading_cwd(self):
        self.process(101)
        self.process(202, parent=101, uid=2000)
        self.process(203, parent=202, group=202, uid=2000)
        self.process(900, uid=2000)  # Same account does not grant run ownership.
        first = self.scan()
        self.assertEqual({p['pid'] for p in first['active']}, {101, 202, 203})
        for path in (self.proc / '101').iterdir():
            path.unlink()
        (self.proc / '101').rmdir()
        self.process(202, parent=1, uid=2000)
        self.process(204, parent=1, group=202, uid=2000)
        after = self.scan()
        self.assertEqual({p['pid'] for p in after['active']}, {202, 203, 204})
        self.assertEqual(after['unscoped_agent_pids'], [900])

    def test_private_exact_identity_survives_deleted_public_registry(self):
        current = self.process(202, parent=1, uid=2000)
        state = self.root / 'session-state'
        state.mkdir()
        (state / 'agent.json').write_text(json.dumps({'native_process': current}))
        self.assertEqual([p['pid'] for p in self.scan()['active']], [202])
        self.assertEqual(self.scan()['registry'], 'missing')

    def test_reused_pid_is_not_adopted_by_stale_or_changed_session_pointer(self):
        self.process(101)
        old = self.process(202, parent=101, uid=2000, ticks=10)
        self.scan()
        replacement = self.process(202, parent=101, uid=2000, ticks=20)
        state = self.root / 'session-state'
        state.mkdir()
        for saved in (old, replacement):
            (state / 'agent.json').write_text(json.dumps({'native_process': saved}))
            self.assertNotIn(202, [p['pid'] for p in self.scan()['active']])
            self.assertEqual(self.known[202]['start_ticks'], 10)

    def test_unreadable_tracked_pid_is_not_a_verified_exit(self):
        self.process(101)
        self.scan()
        (self.proc / '101' / 'stat').write_text('corrupt')
        self.assertEqual(self.scan()['unreadable'], [{'pid': 101, 'error': 'IndexError'}])


class ShutdownOrderingTests(unittest.TestCase):
    def drain(self, *, idle=True, cleanup_error=False):
        actions = []
        service = SimpleNamespace(begin_shutdown=lambda reason: actions.append(('stop', reason)),
            wait_for_idle=lambda **kwargs: actions.append(('idle', kwargs['timeout'])) or idle)
        def server(name):
            return SimpleNamespace(shutdown=lambda: actions.append((name, 'shutdown')),
                server_close=lambda: actions.append((name, 'close')))
        research, grader = server('research'), server('grader')
        def cleanup(*args):
            actions.append(('process', 'cleanup'))
            if cleanup_error:
                raise OSError('private detail must not reach receipt')
            return {'verified_no_active_tracked_processes': True}
        with mock.patch.object(runner, 'stop_native_manager', side_effect=cleanup):
            receipt = runner.drain_native_run(service, object(), Path('.'), 2000, {},
                                              research, grader, None, 'user_interrupt')
        return actions, receipt, research, grader

    def test_stop_admission_then_processes_then_drain_then_close(self):
        actions, receipt, _, _ = self.drain()
        self.assertEqual(actions, [('stop', 'user_interrupt'), ('process', 'cleanup'), ('idle', 190),
            ('research', 'shutdown'), ('research', 'close'), ('grader', 'shutdown'), ('grader', 'close')])
        self.assertTrue(receipt['cleanup_complete'])

    def test_inflight_timeout_prevents_stable_export_and_unbounded_server_join(self):
        _, receipt, research, grader = self.drain(idle=False)
        self.assertFalse(receipt['cleanup_complete'])
        self.assertFalse(research.block_on_close)
        self.assertFalse(grader.block_on_close)

    def test_cleanup_error_does_not_skip_service_and_server_cleanup(self):
        actions, receipt, _, _ = self.drain(cleanup_error=True)
        self.assertIn(('grader', 'close'), actions)
        self.assertTrue(receipt['service_idle'])
        self.assertFalse(receipt['cleanup_complete'])
        self.assertEqual(receipt['errors'], [{'stage': 'native_process_cleanup', 'error_type': 'OSError'}])

    def test_broken_proc_scan_still_requests_manager_stop_and_marks_unverified_cleanup(self):
        process = mock.Mock(pid=123)
        process.poll.side_effect = [None, 0, 0]
        with mock.patch.object(runner, 'track_native_processes', side_effect=OSError), \
                mock.patch.object(runner, 'stop_tracked_processes', side_effect=OSError):
            receipt = runner.stop_native_manager(process, Path('.'), 2000, {})
        process.send_signal.assert_called_once_with(signal.SIGTERM)
        self.assertFalse(receipt['verified_no_active_tracked_processes'])
        self.assertEqual(receipt['process_observation_errors'], ['OSError'])

    def test_absolute_deadline_stops_waiting_on_real_manager_without_resetting_timer(self):
        with tempfile.TemporaryDirectory() as folder:
            process = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
            try:
                with mock.patch.object(runner, 'track_native_processes', return_value={'unreadable': []}):
                    started = time.monotonic()
                    with self.assertRaises(subprocess.TimeoutExpired):
                        runner.wait_native_manager(process, Path(folder), time.time() + 0.12,
                                                   2000, {}, started='offline-fixture')
                self.assertLess(time.monotonic() - started, 2)
                self.assertIsNone(process.poll())  # Supervisor separates waiting from ordered cleanup.
            finally:
                process.terminate()
                process.wait(timeout=5)


class LaunchSettingsTests(unittest.TestCase):
    def test_effective_models_and_limits_are_recorded_without_credentials(self):
        args = SimpleNamespace(max_tools=640, max_attempts=4, wall_seconds=7200)
        config = OpenAIConfig(model='fixture-model', api_key='PRIVATE-KEY', provider='deepseek',
                              endpoint='https://api.deepseek.com', deepseek_thinking='disabled')
        with mock.patch.dict(os.environ, {'SAGE_DSH_BASE_URL': 'https://api.deepseek.com/anthropic'}):
            value = runner.launch_settings(args, config)
        self.assertEqual(value['budgets']['research_tools'], 640)
        self.assertEqual(value['budgets']['formal_attempts'], 4)
        self.assertEqual(value['budgets']['wall_seconds'], 7200)
        for role in ('reader', 'reviewer', 'native_researcher'):
            self.assertEqual(value['model_configuration'][role]['model'], 'fixture-model')
        self.assertEqual(value['model_configuration']['reviewer']['environment_role'], 'main')
        self.assertNotIn('PRIVATE-KEY', json.dumps(value))


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process-group and /proc contract')
class RealNativeShutdownTests(unittest.TestCase):
    def test_real_manager_grace_and_reparented_group_cleanup_leave_unrelated_process_alive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            marker = root / 'child.json'
            child_script = root / 'child.py'
            child_script.write_text('import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n')
            manager_script = root / 'manager.py'
            manager_script.write_text('import json,os,signal,subprocess,sys,time\n'
                'def stop(*args):\n time.sleep(0.25)\n sys.exit(0)\n'
                'signal.signal(signal.SIGTERM,stop)\n'
                f'child=subprocess.Popen([sys.executable,{str(child_script)!r}],start_new_session=True)\n'
                f'open({str(marker)!r},"w").write(json.dumps({{"pid":child.pid}}))\n'
                'time.sleep(60)\n')
            manager = subprocess.Popen([sys.executable, str(manager_script)], start_new_session=True)
            unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'], start_new_session=True)
            known = {}
            child_pid = None
            try:
                end = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < end:
                    time.sleep(0.01)
                child_pid = json.loads(marker.read_text())['pid']
                lifecycle.track_native_processes(manager.pid, root, known, os.getuid())
                self.assertIn(child_pid, known)
                original = runner.stop_tracked_processes
                with mock.patch.object(runner, 'stop_tracked_processes', side_effect=lambda *a:
                                       original(*a, term_seconds=0.1, kill_seconds=2)):
                    started = time.monotonic()
                    receipt = runner.stop_native_manager(manager, root, os.getuid(), known, grace_seconds=1)
                self.assertGreaterEqual(time.monotonic() - started, 0.20)
                self.assertEqual(manager.returncode, 0)
                self.assertTrue(receipt['verified_no_active_tracked_processes'], receipt)
                self.assertIsNone(unrelated.poll())
                self.assertTrue(any(x['pgid'] == child_pid and x['signal'] == 'SIGKILL' for x in receipt['signals']))
            finally:
                for pid in (manager.pid, unrelated.pid, child_pid):
                    if pid:
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                manager.wait(timeout=5)
                unrelated.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
