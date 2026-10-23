"""Local HTTP and lifecycle tests; no scientific/model execution."""
import json
import hashlib
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from sage.console import RunStore, handler_class


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = RunStore(self.root)
        self.run = self.root / 'fixture'
        self.run.mkdir()
        (self.run / 'service-private').mkdir()
        self.put('launch.json', {'topic': 'Synthetic console fixture', 'researchers': 4})

    def put(self, name, value):
        (self.run / name).write_text(json.dumps(value), encoding='utf-8')

    def test_team_complete_does_not_mean_workflow_complete(self):
        self.put('service-private/team-state.json', {'syntheses': [{'document': {'candidates': []}}]})
        self.put('result.json', {'workflow_status': 'incomplete', 'status': 'native_manager_finished'})
        s = self.store.summary('fixture')
        self.assertEqual(s['status'], 'incomplete')
        self.assertEqual(s['stage'], 'synthesis')
        self.assertEqual(s['counts']['formal_completed'], 0)

    def test_native_completed_status_is_shown_without_claiming_scientific_acceptance(self):
        grade = {'evaluation_status': 'completed', 'primary_sha256': 'a'*64, 'review_id': 'review-2'}
        self.put('service-private/evidence.json', {'grades': [grade]})
        self.put('result.json', {'workflow_status': 'completed_autonomous_conjectures', 'selected_grade': grade})
        summary = self.store.summary('fixture')
        self.assertEqual(summary['status'], 'completed')
        self.assertEqual(summary['stage'], 'export')
        self.assertFalse(summary['independent_acceptance'])

    def test_reported_completion_requires_matching_completed_grade(self):
        for grade in ({'score': 0.9}, {'evaluation_status': 'completed', 'primary_sha256': 'wrong', 'review_id': 'review-2'}):
            with self.subTest(grade=grade):
                self.put('service-private/evidence.json', {'grades': [grade]})
                self.put('result.json', {'workflow_status': 'completed_autonomous_conjectures', 'selected_grade': {
                    'evaluation_status': 'completed', 'primary_sha256': 'a'*64, 'review_id': 'review-2'}})
                summary = self.store.summary('fixture')
                self.assertEqual(summary['status'], 'historical_unverified')
                self.assertNotEqual(summary['stage'], 'export')
                self.assertFalse(summary['independent_acceptance'])

    def test_runs_sort_by_actual_start_with_unknown_dates_last(self):
        for ident, started in [('z-old', '2025-01-01T00:00:00Z'), ('a-new', '2026-01-01T09:00:00+08:00'),
                               ('b-middle', '2026-01-01T00:30:00Z'), ('invalid', 'invalid')]:
            run = self.root / ident
            run.mkdir()
            (run / 'launch.json').write_text(json.dumps({'started': started}))
        self.store.control.mkdir()
        (self.store.control / 'console-newest.json').write_text(json.dumps({'started': '2026-02-01T00:00:00Z'}))
        self.assertEqual(self.store.run_ids(), ['console-newest', 'a-new', 'b-middle', 'z-old', 'invalid', 'fixture'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for browser request lifecycle tests')
    def test_browser_selection_and_stale_responses(self):
        subprocess.run([shutil.which('node'), str(Path(__file__).with_name('console_client.test.js'))], check=True, timeout=30)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for planning interaction tests')
    def test_optional_research_planning(self):
        subprocess.run([shutil.which('node'), str(Path(__file__).with_name('planner.test.js'))], check=True, timeout=30)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for reading view tests')
    def test_structured_proposal_and_evidence_reading(self):
        subprocess.run([shutil.which('node'), str(Path(__file__).with_name('reading.test.js'))], check=True, timeout=30)

    def test_editorial_reading_is_bound_to_export_and_existing_fields(self):
        self.put('conjectures.json', {'candidates': [{'id': 'C1', 'problem': 'Synthetic question',
            'protocol': {'variables': [{'id': 'V4', 'definition': 'Synthetic metric'}]}}]})
        (self.run / 'presentation').mkdir()
        reading = {'schema_version': 'sage.proposal-reading.v1',
            'primary_sha256': hashlib.sha256((self.run / 'conjectures.json').read_bytes()).hexdigest(),
            'candidates': {'C1': {'term_names': {'V4': 'Synthetic label', 'V99': 'Unknown ID'}, 'sections': {
                'motivation': {'text': 'Synthetic reading aid', 'source_fields': ['problem']},
                'method': {'text': 'No source field', 'source_fields': ['invented']}}}}}
        self.put('presentation/proposal-reading.json', reading)
        data = self.store.section('fixture', 'overview')['data']['reading']
        self.assertEqual(list(data['C1']['sections']), ['motivation'])
        self.assertEqual(data['C1']['term_names'], {'V4': 'Synthetic label'})
        self.put('conjectures.json', {'candidates': [{'id': 'C1', 'problem': 'Changed question'}]})
        self.assertEqual(self.store.section('fixture', 'overview')['data']['reading'], {})

    def test_researcher_advisory_does_not_advance_synthesis_stage(self):
        self.put('service-private/evidence.json', {'reviews': [{'grading': False, 'research_slot': 2}]})
        self.assertEqual(self.store.summary('fixture')['stage'], 'discovery')

    def test_snapshot_reads_do_not_change_scientific_bytes(self):
        raw = b'{"candidates": []}\n'
        (self.run / 'conjectures.json').write_bytes(raw)
        for section in ('summary', 'input', 'candidates', 'evidence', 'reviews', 'discussion', 'result', 'events'):
            self.store.section('fixture', section)
        self.assertEqual(self.store.artifact('fixture', 'conjectures.json'), raw)
        with self.assertRaises(ValueError):
            self.store.artifact('fixture', 'service-private/evidence.json')

    def test_traversal_and_hidden_run_names_fail_closed(self):
        for ident in ('../secret', '/tmp/secret', 'fixture/../secret', '.console', 'fixture\\secret', ''):
            with self.subTest(ident=ident), self.assertRaises(ValueError):
                self.store.path(ident)

    @unittest.skipUnless(os.name == 'posix', 'Native Linux symlink boundary')
    def test_symlink_in_private_subtree_is_not_followed(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'evidence.json').write_text('{"secret":"unrelated"}')
        (self.run / 'service-private').rmdir()
        (self.run / 'service-private').symlink_to(outside, target_is_directory=True)
        data = self.store.section('fixture', 'evidence')
        self.assertEqual(data['error'], 'unsafe_symlink')
        self.assertNotIn('secret', json.dumps(data))

    def test_inflight_json_is_unavailable_not_success(self):
        (self.run / 'result.json').write_text('{')
        self.assertEqual(self.store.section('fixture', 'result')['error'], 'snapshot_unavailable')
        self.assertNotEqual(self.store.summary('fixture')['status'], 'completed')

    def test_start_requires_double_optin_and_valid_finite_budgets(self):
        with mock.patch('sage.console.subprocess.Popen', side_effect=AssertionError('No scientific calls')):
            with self.assertRaises(ValueError):
                self.store.start({'topic': 'fixture', 'allow_live': True})
            self.store.allow_live = True
            for args in ({'topic': 'fixture', 'allow_live': False}, {'topic': ''}, {'topic': 'fixture', 'max_tools': True},
                         {'topic': 'fixture', 'wall_seconds': 999999}, {'topic': 'fixture', 'max_attempts': 5}):
                with self.assertRaises(ValueError):
                    self.store.start({'allow_live': True, **args})

    def test_start_uses_cli_argv_and_blocks_concurrent_run(self):
        self.store.allow_live = True
        child = mock.Mock(pid=123, poll=mock.Mock(return_value=None))
        # Do not start a reaper for this synthetic child.
        with mock.patch('sage.console.subprocess.Popen', return_value=child) as spawn, \
                mock.patch('sage.console.threading.Thread'):
            result = self.store.start({'topic': 'Synthetic ; not a shell command', 'allow_live': True})
            argv = spawn.call_args.args[0]
            self.assertIn('Synthetic ; not a shell command', argv)
            self.assertIn('--allow-live', argv)
            self.assertNotIn('shell', spawn.call_args.kwargs)
            self.assertFalse((self.root / result['id']).exists(), 'CLI must own output creation')
            with self.assertRaisesRegex(ValueError, 'already active'):
                self.store.start({'topic': 'Duplicate', 'allow_live': True})
            self.assertEqual(spawn.call_count, 1)

    def test_event_view_excludes_raw_responses_secrets_and_thought(self):
        e = {'kind': 'review_failed', 'event_sequence': 4, 'tool': 'critique',
             'partial_response': 'private raw content', 'reasoning': 'not public', 'env': 'secret'}
        (self.run / 'service-private/events.jsonl').write_text(json.dumps(e)+'\n')
        result = self.store.section('fixture', 'events')
        self.assertEqual(result['data'], [{'kind': 'review_failed', 'tool': 'critique', 'event_sequence': 4}])

    def test_http_requires_token_and_same_origin_and_serves_exact_artifact(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_class(self.store, 't'*32))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = 'http://127.0.0.1:' + str(server.server_port)
        for headers in ({}, {'Authorization': 'Bearer '+'t'*32, 'Origin': 'https://evil.example'},
                        {'Authorization': 'Bearer '+'t'*32, 'Host': 'evil.example'}):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base+'/api/runs', headers=headers))
            self.assertEqual(error.exception.code, 401)
        with urlopen(Request(base+'/api/runs', headers={'Authorization':'Bearer '+'t'*32})) as response:
            self.assertEqual(json.load(response)['runs'][0]['id'], 'fixture')
        raw = b'{"candidates":[]}\n'
        (self.run/'conjectures.json').write_bytes(raw)
        with urlopen(Request(base+'/api/artifact?id=fixture&name=conjectures.json',
                             headers={'Authorization':'Bearer '+'t'*32})) as response:
            self.assertEqual(response.read(), raw)


if __name__ == '__main__':
    unittest.main()
