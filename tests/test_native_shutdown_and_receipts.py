"""Offline checks of cancellation, deadline admission and exact failure inputs."""
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from sage.autonomous.service import ResearchService
from sage.errors import InvalidResponse, NoEvidence
from sage.types import Paper


class NativeShutdownAndReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = ResearchService(self.root / 'private', self.root, 'offline topic')

    def events(self):
        return [json.loads(s) for s in (self.service.private / 'events.jsonl').read_text().splitlines()]

    def test_expired_deadline_rejects_before_search_dispatch_and_budget(self):
        self.service.deadline = time.time() - 1
        with mock.patch.object(self.service, 'search', side_effect=AssertionError('No network')):
            with self.assertRaisesRegex(ValueError, 'wall-clock'):
                self.service.call('search', {'query': 'fixture'})
        self.assertEqual(self.service.tool_calls, 0)
        self.assertEqual([e['kind'] for e in self.events()],
                         ['tool_transfer_started', 'tool_transfer_failed'])
        self.assertTrue(self.service.wait_for_idle(0))

    def test_complete_tool_packet_is_retained_for_downstream_byte_check(self):
        self.service.papers = {'p': {'title': 'Fixture source'}}
        self.service.cards = {'p': {'claims': [{'claim': 'Supported fixture'}],
                                    'unverified_claims': [{'claim': 'Uncertain fixture'}],
                                    'source_scope': 'abstract_only'}}
        result = self.service.call('evidence', {})
        terminal = next(e for e in self.events() if e['kind'] == 'tool_transfer_completed')
        expected = json.dumps(result, ensure_ascii=False).encode('utf-8')
        stored = (self.service.private / terminal['output_file']).read_bytes()
        self.assertEqual(stored, expected)
        self.assertEqual(terminal['wire_json_sha256'], hashlib.sha256(stored).hexdigest())
        self.assertEqual(terminal['wire_json_bytes'], len(stored))
        self.assertEqual(json.loads(stored)['cards']['p']['unverified_claims'],
                         [{'claim': 'Uncertain fixture'}])

    def test_shutdown_cancels_registered_async_and_waits_for_cleanup(self):
        entered, cleaned = threading.Event(), threading.Event()
        failures = []
        async def search(**kwargs):
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                await asyncio.sleep(.02)
                cleaned.set()
        def worker():
            try:
                self.service.call('search', {'query': 'fixture'})
            except Exception as error:
                failures.append(str(error))
        with mock.patch.object(self.service, 'search', search):
            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(self.service.wait_for_idle(0))
            self.service.begin_shutdown('user_interrupt')
            self.assertTrue(self.service.wait_for_idle(3))
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(cleaned.is_set())
        self.assertEqual(self.service.shutdown_reason, 'user_interrupt')
        self.assertEqual(self.service.active_async, {})
        self.assertEqual(len(failures), 1)
        self.assertIn('cancelled', failures[0])
        kinds = [e['kind'] for e in self.events()]
        self.assertIn('tool_transfer_failed', kinds)
        self.assertNotIn('tool_transfer_completed', kinds)

    def test_waiting_same_paper_read_is_interruptible_without_new_model(self):
        lock = threading.Lock()
        lock.acquire()
        self.service.read_locks['p'] = lock
        failures = []
        def worker():
            try:
                self.service.call('read', {'paper_id': 'p', 'topic': 'fixture'})
            except Exception as error:
                failures.append(str(error))
        with mock.patch('sage.autonomous.service.OpenAIModel.from_env', side_effect=AssertionError('No model')):
            thread = threading.Thread(target=worker)
            thread.start()
            deadline = time.monotonic() + 2
            while not self.service.inflight and time.monotonic() < deadline:
                time.sleep(.005)
            self.service.begin_shutdown('user_interrupt')
            self.assertTrue(self.service.wait_for_idle(2))
            thread.join(2)
        lock.release()
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(failures), 1)
        self.assertIn('stopping', failures[0])

    def test_repeated_shutdown_does_not_cancel_cleanup_twice(self):
        entered, cleaning, cleaned = threading.Event(), threading.Event(), threading.Event()
        async def search(**kwargs):
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                cleaning.set()
                await asyncio.sleep(.15)
                cleaned.set()
        def worker():
            try:
                self.service.call('search', {'query': 'fixture'})
            except ValueError:
                pass
        with mock.patch.object(self.service, 'search', search):
            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(entered.wait(2))
            self.service.begin_shutdown('user_interrupt')
            self.assertTrue(cleaning.wait(2))
            self.service.begin_shutdown('second_signal')
            self.assertTrue(self.service.wait_for_idle(2))
            thread.join(2)
        self.assertTrue(cleaned.is_set())
        self.assertEqual(self.service.shutdown_reason, 'user_interrupt')

    def test_stop_at_nested_request_boundary_prevents_model_dispatch(self):
        self.service.papers['arxiv:2401.00001'] = asdict(Paper('arxiv:2401.00001', 'Fixture', 'Abstract'))
        class Model:
            calls = 0
            closed = False
            async def complete(self, *args, **kwargs):
                self.calls += 1
                return '<entailment>{}</entailment>'
            async def aclose(self):
                self.closed = True
        model = Model()
        original = self.service.event
        def event(kind, **fields):
            original(kind, **fields)
            if kind == 'capsule_runtime' and fields['event']['status'] == 'request_metadata':
                self.service.begin_shutdown('user_interrupt')
        async def extract(runtime, *args, **kwargs):
            return await runtime.ask('literature.entailment', 'Fixture', ['entailment'])
        with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model), \
             mock.patch('sage.autonomous.service.extract_span_capsule', extract), \
             mock.patch.object(self.service, 'event', event):
            with self.assertRaises(Exception):
                self.service.call('read', {'paper_id': 'arxiv:2401.00001', 'topic': 'fixture'})
        self.assertEqual(model.calls, 0)
        self.assertTrue(model.closed)
        self.assertEqual(self.service.cards, {})

    def test_late_coroutine_is_closed_before_running(self):
        self.service.begin_shutdown('user_interrupt')
        async def operation():
            self.fail('Stopped service executed a coroutine')
        pending = operation()
        with self.assertRaisesRegex(ValueError, 'stopping'):
            self.service.run_async(pending)
        self.assertIsNone(pending.cr_frame)

    def test_unreadable_metadata_fails_before_allocating_model(self):
        self.service.papers['doi:fixture'] = asdict(Paper('doi:fixture', 'Fixture title', ''))
        with mock.patch('sage.autonomous.service.OpenAIModel.from_env', side_effect=AssertionError('No model')):
            with self.assertRaises(NoEvidence):
                self.service.call('read', {'paper_id': 'doi:fixture', 'topic': 'fixture'})

    def test_native_read_retains_exact_rejected_normal_content_privately(self):
        self.service.papers['arxiv:2401.00001'] = asdict(Paper('arxiv:2401.00001', 'Fixture', 'Abstract'))
        class Model:
            closed = False
            async def complete(self, *args, **kwargs):
                return 'ordinary invalid response without the required tag'
            async def aclose(self):
                self.closed = True
        model = Model()
        async def extract(runtime, *args, **kwargs):
            return await runtime.ask('literature.entailment', 'Fixture evidence only', ['entailment'])
        with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model), \
             mock.patch('sage.autonomous.service.extract_span_capsule', extract):
            with self.assertRaises(InvalidResponse):
                self.service.call('read', {'paper_id': 'arxiv:2401.00001', 'topic': 'fixture'})
        paths = list((self.service.private / 'reading-checkpoints').glob('*.json'))
        self.assertEqual(len(paths), 1)
        data = json.loads(paths[0].read_text())['data']
        self.assertGreater(len(data['rejections']), 0)
        self.assertTrue(all(x['raw_response'] == 'ordinary invalid response without the required tag'
                            for x in data['rejections']))
        self.assertTrue(all('raw_request' in x for x in data['rejections']))
        self.assertTrue(model.closed)
        self.assertEqual(self.service.cards, {})
        self.assertIn('read_checkpoint_created', [e['kind'] for e in self.events()])

    def test_rejected_team_input_is_retained_before_parsing_and_later_overwrite(self):
        service = ResearchService(self.root / 'team-private', self.root, 'fixture', researchers=2)
        workspace = self.root / 'native-run' / 'agents' / 'worker'
        workspace.mkdir(parents=True)
        service.team.register(0, 'worker', workspace, 'session-00000000-0000-0000-0000-000000000001')
        path = workspace / 'proposal.json'
        raw = b'{"invalid draft":'
        path.write_bytes(raw)
        with self.assertRaises(ValueError):
            service.call('team', {'action': 'propose', 'artifact_path': str(path)}, slot=0)
        sha = hashlib.sha256(raw).hexdigest()
        path.write_text('{"later": "different draft"}')
        self.assertEqual((service.private / f'team-input-{sha}.json').read_bytes(), raw)
        events = [json.loads(s) for s in (service.private / 'events.jsonl').read_text().splitlines()]
        read_event = next(e for e in events if e['kind'] == 'team_artifact_read')
        failure = next(e for e in events if e['kind'] == 'tool_transfer_failed')
        self.assertEqual(read_event['primary_sha256'], sha)
        self.assertEqual(read_event['request_id'], failure['request_id'])

    def test_stop_while_reading_valid_proposal_prevents_late_freeze(self):
        from test_autonomous_team_service import candidate_document
        from sage.autonomous.service import read_confined
        service = ResearchService(self.root / 'team-private', self.root, 'fixture', researchers=2)
        workspace = self.root / 'native-run' / 'agents' / 'worker'
        workspace.mkdir(parents=True)
        service.team.register(0, 'worker', workspace, 'session-00000000-0000-0000-0000-000000000001')
        service.papers = {f'p{i}': {'paper_id': f'p{i}'} for i in range(12)}
        service.cards = {f'p{i}': {'claims': [{'claim': 'Fixture'}]} for i in range(6)}
        path = workspace / 'proposal.json'
        raw = json.dumps(candidate_document(4)).encode()
        path.write_bytes(raw)
        def stopped_read(*args):
            value = read_confined(*args)
            service.begin_shutdown('user_interrupt')
            return value
        with mock.patch('sage.autonomous.service.read_confined', stopped_read):
            with self.assertRaisesRegex(ValueError, 'stopping'):
                service.call('team', {'action': 'propose', 'artifact_path': str(path)}, slot=0)
        self.assertEqual(service.team.state['proposals'], {})
        sha = hashlib.sha256(raw).hexdigest()
        self.assertEqual((service.private / f'team-input-{sha}.json').read_bytes(), raw)
        self.assertTrue(service.wait_for_idle(0))


if __name__ == '__main__':
    unittest.main()
