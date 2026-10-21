"""Offline lifecycle regressions: completed CORAL workers must not burn models."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sage.autonomous.dsh_runtime import public_event, supervised_argv
from sage.autonomous.lifecycle import resumed_argv, supervise
from sage.autonomous.revision_policy import revision_policy, score_observations


SESSION = 'session-54b62236-a4ad-4f77-881f-217eeac651f2'


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
    def __init__(self, session=SESSION, *, final=True, code=0):
        events = [{'type': 'session', 'sessionId': session, 'cwd': '/fixture'}]
        if final:
            events.append({'type': 'final', 'text': 'done'})
        self.stdout = io.BytesIO(('\n'.join(json.dumps(event) for event in events)).encode())
        self.returncode = code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class LifecycleTests(unittest.TestCase):
    def run_native(self, statuses, *, deadline=100, natives=None, stop=None):
        waiting = stop or VirtualWait()
        emitted, launches = [], []
        statuses = iter(statuses)
        natives = iter(natives or [FinishedNative()])

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

        code = supervise(['/dsh', '--json', '--', 'literal'], 1,
            deadline=deadline, poll_seconds=20, status=status, emit=emitted.append,
            stop=waiting, clock=lambda: waiting.now, launch=launch)
        return code, emitted, launches

    def test_completed_worker_parks_without_additional_model_launches(self):
        code, events, launches = self.run_native([{'slot': 1, 'next_action': 'finished'}])
        self.assertEqual(code, 124)
        self.assertEqual(len(launches), 1)
        self.assertEqual([x['state'] for x in events if x['type'] == 'sage_lifecycle'],
                         ['parked', 'waiting', 'waiting', 'waiting', 'waiting', 'deadline'])

    def test_wait_barrier_resumes_only_authoritative_task_in_same_session(self):
        code, events, launches = self.run_native([
            {'slot': 1, 'next_action': 'wait'},
            {'slot': 1, 'next_action': 'review'},
            {'slot': 1, 'next_action': 'finished'}],
            natives=[FinishedNative(), FinishedNative()])
        self.assertEqual(code, 124)
        self.assertEqual(len(launches), 2)
        self.assertIn('--session-id', launches[1])
        self.assertEqual(launches[1][launches[1].index('--session-id') + 1], SESSION)
        self.assertEqual(sum(x.get('state') == 'resuming' for x in events), 1)

    def test_status_failure_or_other_slot_never_authorizes_model_work(self):
        code, events, launches = self.run_native([
            ValueError('private error'), {'slot': 2, 'next_action': 'review'},
            {'slot': 1, 'next_action': 'finished'}])
        self.assertEqual(code, 124)
        self.assertEqual(len(launches), 1)
        self.assertEqual(sum(x.get('state') == 'status_unavailable' for x in events), 2)
        self.assertNotIn('private error', json.dumps(events))

    def test_incomplete_action_returns_to_coral_without_disguising_completion(self):
        code, events, launches = self.run_native([{'slot': 1, 'next_action': 'revise'}])
        self.assertEqual(code, 0)
        self.assertEqual(len(launches), 1)
        self.assertFalse(any(x.get('state') == 'parked' for x in events))

    def test_crash_or_missing_final_cannot_be_parked_as_finished(self):
        for native in [FinishedNative(final=False), FinishedNative(code=17)]:
            code, events, launches = self.run_native([], natives=[native])
            self.assertNotEqual(code, 0)
            self.assertFalse(any(x.get('state') == 'parked' for x in events))

    def test_changed_session_is_refused_after_resume(self):
        other = 'session-1e476eda-9b9d-4fd9-95ac-3020381d7148'
        code, events, launches = self.run_native([
            {'slot': 1, 'next_action': 'wait'}, {'slot': 1, 'next_action': 'review'}],
            natives=[FinishedNative(), FinishedNative(other)])
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]['state'], 'native_error')

    def test_expired_absolute_deadline_prevents_new_dsh_launch(self):
        code, events, launches = self.run_native([], deadline=0)
        self.assertEqual(code, 124)
        self.assertEqual(launches, [])

    def test_cancelled_park_exits_without_new_model_call(self):
        waiting = VirtualWait()
        original = waiting.wait

        def cancel(timeout):
            original(timeout)
            waiting.cancelled = True
            return True

        waiting.wait = cancel
        code, events, launches = self.run_native([{'slot': 1, 'next_action': 'finished'}], stop=waiting)
        self.assertEqual(code, 0)
        self.assertEqual(len(launches), 1)
        self.assertEqual(events[-1]['state'], 'stopped')

    def test_coordinator_keeps_actual_native_process_and_absolute_worker_deadline(self):
        native = ['/dsh', '--json', '--', 'literal']
        self.assertIs(supervised_argv(native, 0, {}), native)
        first = supervised_argv(native, 1, {'lifecycle_timeout_seconds': 900},
                                environ={'SAGE_RUNTIME_DEADLINE_UNIX': '500'}, now=10)
        restarted = supervised_argv(native, 1, {'lifecycle_timeout_seconds': 900},
                                    environ={'SAGE_RUNTIME_DEADLINE_UNIX': '500'}, now=100)
        self.assertEqual(first, restarted)
        self.assertIn('500.0', first)
        self.assertEqual(first[-len(native):], native)

    def test_lifecycle_public_log_keeps_only_safe_metadata(self):
        event = public_event({'type': 'sage_lifecycle', 'slot': 1, 'state': 'parked',
                              'sessionId': SESSION, 'text': 'private', 'arguments': {'secret': 1}})
        self.assertEqual(event, {'type': 'sage_lifecycle', 'slot': 1, 'state': 'parked', 'sessionId': SESSION})
        self.assertIsNone(public_event({'type': 'sage_lifecycle', 'slot': 0, 'state': 'parked'}))


class RealSupervisorTests(unittest.TestCase):
    def test_real_worker_process_remains_alive_then_resumes_and_cancels(self):
        """Use an actual subprocess and local HTTP server; no DSH/API/CORAL install."""
        state = {'action': 'wait', 'polls': 0}

        class FixtureServer(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                # Windows terminate closes an in-flight loopback socket; this
                # expected cancellation is unrelated to lifecycle correctness.
                if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
                    return
                super().handle_error(request, client_address)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.assert_request = request
                state['polls'] += 1
                body = json.dumps({'slot': 1, 'next_action': state['action']}).encode()
                if state['action'] == 'review':
                    # A single authoritative task; the fake native worker
                    # completes it immediately before the next status query.
                    state['action'] = 'finished'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = FixtureServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'native.py'
            counter = root / 'launches.jsonl'
            script.write_text('import json,sys,os\nfrom pathlib import Path\n'
                f'p=Path({str(counter)!r})\n'
                'with p.open("a") as stream: stream.write(json.dumps({"argv":sys.argv[1:],'
                '"deadline":os.environ.get("SAGE_RUNTIME_DEADLINE_UNIX")})+"\\n")\n'
                f'print(json.dumps({{"type":"session","sessionId":{SESSION!r},"cwd":os.getcwd()}}),flush=True)\n'
                'print(json.dumps({"type":"final","text":"done"}),flush=True)\n', encoding='utf-8')
            deadline = str(time.time() + 20)
            env = dict(os.environ, SAGE_RESEARCH_PORT=str(server.server_port),
                       SAGE_RESEARCH_TOKEN='offline-fixture-token', SAGE_RUNTIME_DEADLINE_UNIX=deadline)
            process = subprocess.Popen([sys.executable, '-m', 'sage.autonomous.lifecycle',
                '--slot', '1', '--deadline', deadline, '--poll-seconds', '0.05',
                '--', sys.executable, str(script), '--json', '--', 'initial'],
                cwd=Path(__file__).resolve().parents[1], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                end = time.time() + 8
                while state['polls'] < 3 and time.time() < end:
                    time.sleep(0.02)
                self.assertGreaterEqual(state['polls'], 3)
                self.assertIsNone(process.poll(), 'CORAL must see a real alive worker while parked')
                self.assertEqual(len(counter.read_text().splitlines()), 1)
                state['action'] = 'review'
                while len(counter.read_text().splitlines()) < 2 and time.time() < end:
                    time.sleep(0.02)
                state['action'] = 'finished'
                launches = [json.loads(x) for x in counter.read_text().splitlines()]
                self.assertEqual(len(launches), 2)
                self.assertIn(SESSION, launches[1]['argv'])
                self.assertIn('--session-id', launches[1]['argv'])
                self.assertEqual([launch['deadline'] for launch in launches], [deadline, deadline])
                time.sleep(0.15)
                self.assertEqual(len(counter.read_text().splitlines()), 2)
                process.terminate()
                stdout, stderr = process.communicate(timeout=5)
                self.assertNotIn('offline-fixture-token', stdout + stderr)
                self.assertNotIn('Traceback', stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)

    def test_real_active_native_subprocess_is_stopped_at_absolute_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'long_native.py'
            script.write_text('import json,os,time\n'
                f'print(json.dumps({{"type":"session","sessionId":{SESSION!r},"cwd":os.getcwd()}}),flush=True)\n'
                'time.sleep(60)\n', encoding='utf-8')
            process = subprocess.Popen([sys.executable, '-m', 'sage.autonomous.lifecycle',
                '--slot', '1', '--deadline', str(time.time() + 2), '--',
                sys.executable, str(script), '--json', '--', 'fixture'],
                cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, start_new_session=(os.name == 'posix'))
            try:
                stdout, stderr = process.communicate(timeout=8)
                self.assertEqual(process.returncode, 124, stderr)
                events = [json.loads(line) for line in stdout.splitlines()]
                self.assertTrue(any(event.get('type') == 'session' for event in events))
                self.assertTrue(any(event.get('state') == 'deadline' for event in events))
                self.assertNotIn('Traceback', stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)


class RevisionPolicyTests(unittest.TestCase):
    def test_only_exact_numeric_prompt_and_model_pairs_show_observed_dispersion(self):
        receipts = [{'id': f'r{i}', 'review_prompt_sha256': digest,
                     'reviewer_model': model, 'review': {'score': score}}
                    for i, (digest, model, score) in enumerate([
                        ('a' * 64, 'fixture', 0.82), ('a' * 64, 'fixture', 0.76),
                        ('b' * 64, 'fixture', 0.90), ('a' * 64, 'different', 0.10)])]
        result = score_observations(receipts)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['observed_range'], 0.06)
        self.assertEqual(result[0]['calibration'], 'none')
        self.assertEqual(result[0]['scientific_quality_change'], 'not_established')

    def test_missing_hash_or_invalid_score_cannot_create_fake_repeat_measurements(self):
        base = {'review_prompt_sha256': 'a' * 64, 'reviewer_model': 'fixture'}
        receipts = [{**base, 'review': {'score': value}} for value in (True, float('nan'), 2)]
        receipts += [{'reviewer_model': 'fixture', 'review': {'score': 0.5}}] * 2
        self.assertEqual(score_observations(receipts), [])
        policy = revision_policy()
        self.assertFalse(policy['single_score_rollback'])
        self.assertFalse(policy['request_extra_calls'])


if __name__ == '__main__':
    unittest.main()
