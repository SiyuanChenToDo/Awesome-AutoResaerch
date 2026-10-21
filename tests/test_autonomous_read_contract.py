"""Actual native read wiring with local provider responses, never paid APIs."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sage.autonomous.service import ResearchService
from sage.config import RunConfig
from sage.errors import ConfigurationError
from sage.types import Paper


class LocalPaperModel:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def complete(self, stage, prompt, *, max_tokens):
        self.calls.append((stage, prompt))
        if stage == 'literature.span_capsule':
            return '<capsule>' + json.dumps({'claims': [
                {'category': 'method', 'claim': 'The fixture method uses matched controls.', 'span_ids': ['P1']}],
                'inferences': []}) + '</capsule>'
        if stage == 'literature.entailment':
            batch = json.loads(prompt.split('INPUT_CLAIMS_AND_ORIGINAL_PASSAGES: ', 1)[1])
            return '<entailment>' + json.dumps({'claims': [
                {'claim_id': item['claim_id'], 'verdict': 'supported',
                 'source_span_ids': list(item['source_spans']),
                 'reason': 'The local fixture explicitly states matched controls.', 'unsupported_details': []}
                for item in batch]}) + '</entailment>'
        raise AssertionError('Unexpected model stage: ' + stage)

    async def aclose(self):
        self.closed = True


class NativeReadContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.service = ResearchService(self.root / 'private', self.root, 'RUN_QUESTION')
        self.service.papers['fixture-paper'] = asdict(Paper('fixture-paper', 'Synthetic local fixture',
            abstract='The fixture method uses matched controls.'))
        self.model = LocalPaperModel()
        self.factory = mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=self.model).start()
        self.network = mock.patch('sage.literature.reader._metadata_https_request',
                                  side_effect=AssertionError('No paper network in offline test')).start()
        self.addCleanup(mock.patch.stopall)

    async def test_uncached_native_read_uses_valid_config_real_extraction_and_run_topic(self):
        # Do not mock extract_span_capsule: its actual Runtime, source binding,
        # semantic screen and archive write must all run with native config.
        result = await self.service.read('fixture-paper', 'FIRST_READER_FOCUS')
        self.assertEqual(result['extraction_topic'], 'RUN_QUESTION')
        self.assertTrue(result['claims'])
        self.assertEqual([stage for stage, _ in self.model.calls],
                         ['literature.span_capsule', 'literature.entailment'])
        for _, prompt in self.model.calls:
            self.assertIn('RUN_QUESTION', prompt)
            self.assertNotIn('FIRST_READER_FOCUS', prompt)
        self.assertEqual(result['read_request']['requested_topic'], 'FIRST_READER_FOCUS')
        self.assertFalse(result['read_request']['cache_hit'])
        self.assertEqual(result['read_request']['focus_status'], 'requested_focus_not_separately_extracted')
        self.assertIn('passages', result['read_request']['next_action'])
        self.assertTrue(self.model.closed)
        self.assertTrue(self.service.archives['fixture-paper']['source_sha256'])
        stored = json.loads((self.root / 'private' / 'evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['cards']['fixture-paper']['extraction_topic'], 'RUN_QUESTION')
        self.assertNotIn('read_request', stored['cards']['fixture-paper'])
        self.network.assert_not_called()

    async def test_cached_different_focus_has_own_receipt_without_new_model_or_mutating_card(self):
        first = await self.service.read('fixture-paper', 'FIRST_READER_FOCUS')
        saved = copy.deepcopy(self.service.cards['fixture-paper'])
        second = await self.service.read('fixture-paper', 'SECOND_READER_FOCUS')
        third = await self.service.read('fixture-paper', 'RUN_QUESTION')
        self.factory.assert_called_once()
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(first['claims'], second['claims'])
        self.assertTrue(second['read_request']['cache_hit'])
        self.assertEqual(second['read_request']['requested_topic'], 'SECOND_READER_FOCUS')
        self.assertFalse(second['read_request']['requested_topic_matches_extraction'])
        self.assertTrue(third['read_request']['requested_topic_matches_extraction'])
        self.assertEqual(third['read_request']['focus_status'], 'shared_topic_card')
        self.assertEqual(self.service.cards['fixture-paper'], saved)
        events = [json.loads(line) for line in (self.root / 'private' / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
        returned = [event for event in events if event['kind'] == 'read_returned']
        self.assertEqual([event['requested_topic'] for event in returned],
                         ['FIRST_READER_FOCUS', 'SECOND_READER_FOCUS', 'RUN_QUESTION'])
        outline = self.service.passages('fixture-paper')
        exact = self.service.passages('fixture-paper', [outline['outline'][0]['chunk_id']])
        self.assertIn('matched controls', exact['chunks'][0]['text'])
        self.factory.assert_called_once()

    async def test_legacy_card_does_not_invent_extraction_topic(self):
        self.service.cards['fixture-paper'] = {'paper_id': 'fixture-paper', 'claims': []}
        result = await self.service.read('fixture-paper', 'RUN_QUESTION')
        self.assertIsNone(result['read_request']['extraction_topic'])
        self.assertIsNone(result['read_request']['requested_topic_matches_extraction'])
        self.assertEqual(result['read_request']['focus_status'], 'legacy_extraction_topic_unknown')
        self.factory.assert_not_called()

    async def test_config_validation_precedes_model_allocation(self):
        with mock.patch('sage.autonomous.service.RunConfig', side_effect=ConfigurationError('Invalid fixture config')):
            with self.assertRaises(ConfigurationError):
                await self.service.read('fixture-paper', 'FIRST_READER_FOCUS')
        self.factory.assert_not_called()

    async def test_runtime_construction_failure_still_closes_allocated_client(self):
        with mock.patch('sage.autonomous.service.Runtime', side_effect=RuntimeError('Fixture initialization failure')):
            with self.assertRaises(RuntimeError):
                await self.service.read('fixture-paper', 'FIRST_READER_FOCUS')
        self.assertTrue(self.model.closed)
        self.assertFalse(self.service.cards)

    async def test_invalid_requested_topic_does_not_call_provider(self):
        for topic in (None, '', '  ', 3):
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                await self.service.read('fixture-paper', topic)
        self.factory.assert_not_called()

    def test_native_capacity_is_legal_without_changing_small_defaults(self):
        self.assertEqual(RunConfig(capsule_max_chars=240000).capsule_max_chars, 240000)
        self.assertEqual(RunConfig().capsule_max_chars, 12000)
        for size in (240001, 1999, True):
            with self.subTest(size=size), self.assertRaises(ConfigurationError):
                RunConfig(capsule_max_chars=size)


if __name__ == '__main__':
    unittest.main()
