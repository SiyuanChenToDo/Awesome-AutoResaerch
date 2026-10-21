"""Offline launcher signal regressions; no native manager or model is started."""
from contextlib import ExitStack, redirect_stdout
import io
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
from sage.providers import OpenAIConfig, OpenAIModel
from sage.errors import RequestCapacityError


class NativeSignalTests(unittest.TestCase):
    def test_old_interrupted_error_handler_is_swallowed_by_real_proc_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc = root / 'proc'
            (proc / '123').mkdir(parents=True)
            received = []
            def legacy_handler(signum, frame):
                received.append(signal.Signals(signum).name)
                raise InterruptedError('Autonomous research interrupted')
            def interrupted_identity(*args):
                signal.raise_signal(signal.SIGTERM)
                self.fail('Legacy handler must raise')
            previous = signal.signal(signal.SIGTERM, legacy_handler)
            try:
                with mock.patch.object(lifecycle, 'process_identity', side_effect=interrupted_identity):
                    value = lifecycle.track_native_processes(123, root, {}, 1000, proc_root=proc)
            finally:
                signal.signal(signal.SIGTERM, previous)
            self.assertEqual(received, ['SIGTERM'])
            self.assertEqual(value['unreadable'], [{'pid': 123, 'error': 'InterruptedError'}])

    def test_preexisting_stop_is_checked_before_scanning_or_waiting(self):
        process = mock.Mock(pid=123)
        with mock.patch.object(runner, 'track_native_processes') as scan:
            with self.assertRaises(runner.NativeStopRequested):
                runner.wait_native_manager(process, Path('.'), time.time() + 60, 1000, {},
                                           started='fixture', stop_requested=lambda: True)
        scan.assert_not_called()
        process.poll.assert_not_called()
        process.wait.assert_not_called()

    def test_default_callback_remains_compatible_with_normal_manager_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            process = mock.Mock(pid=123)
            process.poll.return_value = 0
            with mock.patch.object(runner, 'track_native_processes', return_value={'unreadable': []}):
                self.assertEqual(runner.wait_native_manager(process, Path(folder),
                    time.time() + 60, 1000, {}, started='fixture'), 0)
            process.wait.assert_not_called()

    def launch_fixture(self, stage, signum=signal.SIGTERM):
        """Exercise run's actual handlers/cleanup boundaries, replacing external work."""
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            destination = root / 'run'
            destination.mkdir()
            dsh = root / 'dsh'
            dsh.write_text('offline fixture')
            proc = root / 'proc'
            (proc / '123').mkdir(parents=True)
            args = SimpleNamespace(allow_live=True, coral_python=Path(sys.executable),
                aris_root=root, dsh=dsh, agent_user='fixture', topic='Offline fixture',
                max_tools=640, max_attempts=4, wall_seconds=7200, researchers=4,
                discussion_rounds=2)
            service = SimpleNamespace(deadline=time.time() + 60, shutdown_reason=None,
                save=mock.Mock(), private=root / 'private', grades=[], reviews=[], team=None,
                papers={}, cards={}, searches=[], formal_attempts=0)
            guard_failure = stage in ('guard_failure', 'guard_corrupt')
            post_failure = stage in ('error_save', 'error_export', 'error_source')
            selected_grade = ({'primary_sha256': 'fixture', 'evaluation_status': 'completed'}
                              if guard_failure else None)
            if selected_grade:
                service.grades = [selected_grade]
            server = SimpleNamespace(server_port=12345)
            received, scans, cleanup_calls = [], [], []
            def interrupt(where):
                if stage == 'error_' + where:
                    received.append(stage)
                    raise ValueError('sensitive failure message must never enter terminal artifacts')
                if stage == where and not received:
                    received.append(where)
                    signal.raise_signal(signum)
            def prepare(*args, **kwargs):
                (destination / 'aris-inputs.json').write_text(json.dumps({'coral_task_sha256': 'fixture'}))
            def serve(*args):
                interrupt('server')
                return server
            def poll():
                if post_failure:
                    return 0
                if guard_failure:
                    received.append(stage)
                    (destination / 'runtime-crash.json').write_text(
                        '{broken' if stage == 'guard_corrupt' else
                        json.dumps({'schema_version': 'sage.native_owner_failure.v1',
                                    'reason': 'owner_unverifiable'}))
                    return 0
                interrupt('poll')
                return 0 if stage == 'poll' else None
            def wait(**kwargs):
                interrupt('wait')
                raise subprocess.TimeoutExpired('fixture', kwargs['timeout'])
            process = mock.Mock(pid=123, args=['fixture'], poll=poll, wait=wait)
            def launch(*args, **kwargs):
                interrupt('popen')
                return process
            def identity(pid, proc_root):
                interrupt('scan')
                return {'pid': pid, 'ppid': 1, 'pgid': pid, 'sid': pid,
                        'start_ticks': 10, 'uid': 0, 'state': 'S'}
            def scan(pid, path, known, uid):
                value = lifecycle.track_native_processes(pid, path, known, uid, proc_root=proc)
                scans.append(value)
                return value
            def drain(*arguments):
                cleanup_calls.append(arguments)
                # Repeated stop signals must not interrupt or relabel cleanup.
                signal.raise_signal(signal.SIGTERM)
                signal.raise_signal(signal.SIGINT)
                return {'service_idle': True, 'verified_no_active_tracked_processes': True,
                        'cleanup_complete': True, 'errors': []}
            source_calls = []
            def sources(*args):
                if source_calls:
                    interrupt('source')
                source_calls.append(True)
                return {}
            def export(*args):
                interrupt('export')
                return {'selected_grade': selected_grade, 'best_score_grade': selected_grade,
                        'policy': 'offline_fixture'}
            service.save.side_effect = lambda: interrupt('save')
            environment = {'SAGE_OPENAI_API_KEY': 'offline-fixture', 'SAGE_MODEL_PROVIDER': 'deepseek',
                           'SAGE_NATIVE_HOME': str(root)}
            stack.enter_context(mock.patch.object(runner, 'os', SimpleNamespace(
                name='posix', environ=environment, geteuid=lambda: 0, pathsep=os.pathsep)))
            stack.enter_context(mock.patch.dict(sys.modules, {'pwd': SimpleNamespace(
                getpwnam=lambda name: SimpleNamespace(pw_uid=1000, pw_gid=1000))}))
            stack.enter_context(mock.patch('importlib.util.find_spec', return_value=object()))
            stack.enter_context(mock.patch.object(OpenAIConfig, 'from_env', return_value=SimpleNamespace(model='fixture')))
            capacity = stack.enter_context(mock.patch.object(OpenAIModel, 'preflight',
                return_value={'status': 'passed', 'measurement_scope': 'offline_fixture'}))
            if stage == 'capacity':
                capacity.side_effect = RequestCapacityError('tokenizer_asset_missing', {})
            replacements = {'require_pin': mock.Mock(), 'source_manifest': sources,
                'launcher_identity': mock.Mock(return_value={'pid': 999, 'start_ticks': 100,
                    'uid': 0, 'pgid': 999, 'sid': 999, 'ppid': 1, 'state': 'R'}),
                'launch_settings': mock.Mock(return_value={'budgets': {}}), 'prepare': prepare,
                'ResearchService': mock.Mock(return_value=service), 'serve': serve,
                'serve_grader': mock.Mock(return_value=(server, None)),
                'track_native_processes': scan, 'drain_native_run': drain,
                'command': mock.Mock(side_effect=[str(root), '{"resolved_task_sha256":"fixture"}', '{}', '']),
                'export_submissions': mock.Mock(side_effect=export)}
            for name, replacement in replacements.items():
                stack.enter_context(mock.patch.object(runner, name, replacement))
            stack.enter_context(mock.patch.object(runner.shutil, 'which', return_value='fixture'))
            spawn = stack.enter_context(mock.patch.object(runner.subprocess, 'Popen', side_effect=launch))
            stack.enter_context(mock.patch.object(lifecycle, 'process_identity', side_effect=identity))
            previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
            if stage == 'capacity':
                with self.assertRaises(RequestCapacityError):
                    runner.run(args, destination)
                spawn.assert_not_called()
                replacements['ResearchService'].assert_not_called()
                self.assertFalse((destination / 'launch.json').exists())
                return
            with redirect_stdout(io.StringIO()):
                self.assertEqual(runner.run(args, destination), 1)
            for sig, handler in previous.items():
                self.assertIs(signal.getsignal(sig), handler)
            result = json.loads((destination / 'result.json').read_text())
            self.assertEqual(received, [stage])
            failed = stage.startswith('error_') and not post_failure
            expected_reason = ('runtime_supervision_failed' if guard_failure else
                               'finalization_exception' if post_failure else
                               'launcher_exception' if failed else 'user_interrupt')
            self.assertEqual(result['status'], 'failed' if failed or guard_failure or post_failure else 'interrupted')
            self.assertEqual(result['stop_reason'], expected_reason)
            self.assertEqual(result['stop_signal'], None if failed or guard_failure or post_failure else signal.Signals(signum).name)
            self.assertEqual(result['launcher_error'], {'error_type': 'ValueError',
                'stage': 'native_supervision'} if failed else None)
            self.assertNotIn('sensitive failure message', json.dumps(result))
            if post_failure:
                expected_stage = {'error_save': 'service_persistence', 'error_export': 'export_selection',
                                  'error_source': 'source_verification'}[stage]
                self.assertEqual(result['finalization_errors'],
                                 [{'stage': expected_stage, 'error_type': 'ValueError'}])
            else:
                self.assertEqual(result['finalization_errors'], [])
            self.assertEqual(result['workflow_status'], 'incomplete')
            self.assertEqual(capacity.call_count, 2)

            self.assertEqual(len(cleanup_calls), 1)
            self.assertEqual(cleanup_calls[0][-1], 'manager_exited' if guard_failure or post_failure else expected_reason)
            self.assertEqual(result['shutdown']['cleanup_complete'], True)
            self.assertEqual(result['graded_attempts'], 1 if guard_failure else 0)
            if guard_failure:
                self.assertEqual(result['runtime_crash']['readable'], stage != 'guard_corrupt')
                self.assertEqual(result['selected_grade'], selected_grade)
                self.assertEqual(result['stop_reason'], 'runtime_supervision_failed')
            else:
                self.assertIsNone(result['runtime_crash'])
            if stage in ('server', 'error_server', 'error_popen'):
                if stage != 'error_popen':
                    spawn.assert_not_called()
                else:
                    spawn.assert_called_once()
                self.assertIsNone(cleanup_calls[0][1])
            else:
                spawn.assert_called_once()
                self.assertIs(cleanup_calls[0][1], process)
            if spawn.called:
                environment = spawn.call_args.kwargs['env']
                self.assertEqual(environment['SAGE_LAUNCHER_PID'], '999')
                self.assertEqual(environment['SAGE_LAUNCHER_START_TICKS'], '100')
                self.assertEqual(environment['SAGE_RUN_ROOT'], str(destination))
            self.assertEqual(json.loads((destination / 'launch.json').read_text())['launcher_identity'],
                             replacements['launcher_identity'].return_value)
            return scans

    def test_missing_capacity_asset_stops_before_native_research_or_service(self):
        self.launch_fixture('capacity')

    def test_actual_sigterm_inside_proc_read_is_recorded_then_reaches_cleanup(self):
        scans = self.launch_fixture('scan')
        self.assertEqual(len(scans), 1)
        self.assertEqual(scans[0]['unreadable'], [])
        self.assertEqual(scans[0]['active'][0]['pid'], 123)

    def test_actual_sigint_inside_proc_read_keeps_original_signal_during_cleanup(self):
        self.launch_fixture('scan', signal.SIGINT)

    def test_signal_during_process_poll_wins_over_simultaneous_clean_exit(self):
        self.launch_fixture('poll')

    def test_signal_during_bounded_wait_is_observed_on_next_iteration(self):
        self.launch_fixture('wait')

    def test_signal_during_server_start_prevents_manager_launch(self):
        self.launch_fixture('server')

    def test_signal_during_popen_does_not_lose_the_returned_manager(self):
        self.launch_fixture('popen')

    def test_unexpected_supervision_exception_keeps_failure_and_actual_cleanup(self):
        self.launch_fixture('error_poll')

    def test_server_start_exception_keeps_failed_terminal_without_manager(self):
        self.launch_fixture('error_server')

    def test_manager_launch_exception_keeps_failed_terminal_without_process(self):
        self.launch_fixture('error_popen')

    def test_manager_guard_failure_prevents_success_even_with_valid_grade_and_clean_exit(self):
        self.launch_fixture('guard_failure')

    def test_corrupt_manager_failure_receipt_cannot_be_interpreted_as_success(self):
        self.launch_fixture('guard_corrupt')

    def test_service_persistence_error_still_writes_safe_failed_terminal(self):
        self.launch_fixture('error_save')

    def test_rejected_export_is_preserved_as_failure_with_terminal_result(self):
        self.launch_fixture('error_export')

    def test_final_source_verification_error_still_writes_failed_terminal(self):
        self.launch_fixture('error_source')


if __name__ == '__main__':
    unittest.main()
