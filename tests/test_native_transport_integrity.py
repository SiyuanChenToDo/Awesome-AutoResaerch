"""Lossless native JSON boundary tests; installed-runtime smoke is separate."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sage.autonomous.mcp import MAX_TOOL_RESULT_BYTES, request_service, result_content
from sage.autonomous.runner import prepare
from sage.autonomous.skills import REQUIRED_REFERENCES, REQUIRED_SKILLS


class NativeTransportIntegrityTests(unittest.TestCase):
    def test_configured_module_entrypoint_initializes_and_lists_tools_without_a_model(self):
        requests = '\n'.join(json.dumps({'jsonrpc': '2.0', 'id': index, 'method': method})
                             for index, method in enumerate(('initialize', 'tools/list'), 1)) + '\n'
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
            process = subprocess.run([sys.executable, '-m', 'sage.autonomous.mcp'],
                input=requests, text=True, capture_output=True, cwd=folder, env=env, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([row['id'] for row in rows], [1, 2])
        self.assertEqual(rows[0]['result']['serverInfo']['name'], 'sage-research')
        self.assertIn('read', {tool['name'] for tool in rows[1]['result']['tools']})

    def test_large_unicode_packet_preserves_semantic_tail_and_valid_json(self):
        value = {'claims': [{'claim': '原文条件与结果。' * 14000, 'verdict': 'supported'}],
                 'unverified_claims': [{'claim': 'Do not approve this tail claim.',
                                        'entailment_audit': {'verdict': 'uncertain', 'reason': 'Missing support.'}}],
                 'coverage': {'partial_document': True, 'source_scope': 'abstract_only'},
                 'read_request': {'focus_status': 'requested_focus_not_separately_extracted'}}
        encoded = json.dumps(value, ensure_ascii=False)
        self.assertGreater(len(encoded.encode()), 50000)
        result = result_content(value)
        self.assertFalse(result['isError'])
        self.assertEqual(result['content'][0]['text'], encoded)
        self.assertEqual(json.loads(result['content'][0]['text']), value)

    def test_bound_is_utf8_bytes_and_refuses_without_partial_claims(self):
        with patch('sage.autonomous.mcp.MAX_TOOL_RESULT_BYTES', 150):
            result = result_content({'claims': ['汉' * 100]})
        error = json.loads(result['content'][0]['text'])
        self.assertTrue(result['isError'])
        self.assertEqual(error['code'], 'tool_result_too_large')
        self.assertEqual(error['limit_bytes'], 150)
        self.assertGreater(error['observed_bytes_at_least'], 150)
        self.assertNotIn('claims', error)
        self.assertEqual(error['result_scope'], 'complete_result_refused_no_partial_evidence')
        self.assertIn('read(paper_id', error['next_action'])
        self.assertIn('passages(paper_id)', error['next_action'])

    def test_exact_bound_is_allowed_and_next_byte_is_explicit_refusal(self):
        value = {'claims': ['fixed fixture'], 'unverified_claims': []}
        size = len(json.dumps(value, ensure_ascii=False).encode())
        with patch('sage.autonomous.mcp.MAX_TOOL_RESULT_BYTES', size):
            self.assertFalse(result_content(value)['isError'])
        with patch('sage.autonomous.mcp.MAX_TOOL_RESULT_BYTES', size - 1):
            self.assertTrue(result_content(value)['isError'])

    def test_http_reader_never_decodes_a_shortened_success_body(self):
        body = json.dumps({'claims': ['fixture ' * 1000]}).encode()
        with patch.dict(os.environ, SAGE_RESEARCH_PORT='12345', SAGE_RESEARCH_TOKEN='fixture-local-token'), \
                patch('sage.autonomous.mcp.urlopen', return_value=io.BytesIO(body)), \
                patch('sage.autonomous.mcp.MAX_TOOL_RESULT_BYTES', 100):
            result = request_service('read', {'paper_id': 'fixture'})
        self.assertEqual(result['code'], 'tool_result_too_large')
        self.assertEqual(result['observed_bytes_at_least'], 101)
        self.assertNotIn('claims', result)

    def test_http_reader_and_mcp_render_preserve_allowed_body_exactly(self):
        value = {'claims': ['text ' * 14000], 'unverified_claims': [{'verdict': 'unsupported'}],
                 'coverage': {'partial_document': True}}
        body = json.dumps(value, ensure_ascii=False).encode()
        with patch.dict(os.environ, SAGE_RESEARCH_PORT='12345', SAGE_RESEARCH_TOKEN='fixture-local-token'), \
                patch('sage.autonomous.mcp.urlopen', return_value=io.BytesIO(body)):
            received = request_service('evidence', {})
        self.assertEqual(received, value)
        self.assertEqual(result_content(received)['content'][0]['text'].encode(), body)

    def test_official_retention_thresholds_cover_complete_allowed_mcp_packets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in REQUIRED_SKILLS:
                path = root / 'ARIS' / 'skills' / name / 'SKILL.md'
                path.parent.mkdir(parents=True)
                path.write_text('Original fixture skill: ' + name)
            for name in REQUIRED_REFERENCES:
                path = root / 'ARIS' / 'skills' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('Original fixture reference: ' + name)
            prepare(root, topic='Fixture direction', aris_root=root / 'ARIS',
                    coral_python=Path('/python'), dsh=Path('/dsh'), agent_user='fixture')
            text = (root / 'research.patch.yml').read_text()
            self.assertIn('- id: spill-policy\n  config:\n    maxInlineTokens: ' + str(MAX_TOOL_RESULT_BYTES + 256), text)
            self.assertIn('- id: tool-result-pruner\n  config:\n    thresholdChars: ' + str(MAX_TOOL_RESULT_BYTES), text)
            self.assertNotIn('maxInlineTokens: 0', text)
            self.assertNotIn('thresholdChars: 0', text)
            self.assertIn('@deepseek-ai/dsh-mcp-client', text)
            self.assertIn('args: ["-m", "sage.autonomous.mcp"]', text)
            self.assertIn('PYTHONPATH:', text)


if __name__ == '__main__':
    unittest.main()
