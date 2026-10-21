import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from sage.autonomous.repair import ReviewStageError
from sage.autonomous.review import scientific_input
from sage.autonomous.revision_policy import score_observations
from sage.autonomous.service import ResearchService
from test_autonomous_review import primary_document, fixture_review, fixture_feedback


class StageRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.service = ResearchService(root / 'private', root, 'Fixture only', max_tools=10)
        self.service.papers = {ident: {'paper_id': ident, 'title': 'Fixture ' + ident}
                               for ident in ('p1', 'p2', 'p3', 'p4')}
        self.primary = primary_document()
        self.scientific, _ = scientific_input(self.primary, 'Fixture only')
        self.review = fixture_review(self.scientific)
        self.feedback = fixture_feedback(self.scientific, self.review)

    def run_responses(self, responses):
        self.model = SimpleNamespace(config=SimpleNamespace(model='fixture'),
            last_response_model='fixture', last_response_id='fixture-response',
            last_usage={'total_tokens': 7},
            complete=AsyncMock(side_effect=[json.dumps(x) for x in responses]), aclose=AsyncMock())
        with patch('sage.autonomous.service.OpenAIModel.from_env', return_value=self.model):
            return asyncio.run(self.service.judgment(json.dumps(self.primary), 'Fixture focus'))

    def test_missing_evidence_limit_repairs_only_novelty_and_retains_numeric(self):
        bad = copy.deepcopy(self.feedback)
        del bad['candidate_assessments'][0]['claims'][0]['evidence_limit']
        receipt = self.run_responses([self.review, bad, self.feedback])
        self.assertEqual([x.args[0] for x in self.model.complete.await_args_list],
                         ['autonomous.scientific_review', 'autonomous.novelty_feedback',
                          'autonomous.novelty_feedback'])
        self.assertEqual(receipt['review']['score'], 0.8)
        self.assertEqual(len(receipt['model_calls']), 3)
        self.assertEqual(receipt['model_calls'][1]['validation'], 'failed')
        self.assertEqual(self.service.tool_calls, 1)  # extra repair consumes budget
        self.assertEqual(self.service.review_model_calls, 3)
        self.assertIn('evidence_limit', self.model.complete.await_args_list[2].args[1])
        self.assertEqual(len(self.service.reviews), 1)

    def _bad_reference_feedback(self):
        bad = copy.deepcopy(self.feedback)
        bad['candidate_assessments'][0]['claims'][0]['source_refs'] = [
            {'source_id': 'p1', 'reference_id': 'card:FAKE'}]
        return bad

    def test_validation_detail_echoes_to_repair_suffix_and_error_details(self):
        bad = self._bad_reference_feedback()
        receipt = self.run_responses([self.review, bad, self.feedback])
        self.assertEqual(receipt['review']['score'], 0.8)
        repair_prompt = self.model.complete.await_args_list[2].args[1]
        marker = '\n\n{"task": "Repair only'
        self.assertIn(marker, repair_prompt)
        suffix = json.loads('{"task": "Repair only' +
                            repair_prompt.split(marker, 1)[1])
        detail = suffix['validation_detail']
        self.assertEqual(detail['reason'], 'unknown_reference_id')
        self.assertEqual(detail['candidate_id'], 'C1')
        self.assertEqual(detail['offending'],
                         [{'source_id': 'p1', 'reference_id': 'card:FAKE',
                           'reason': 'unknown_reference_id'}])
        self.assertEqual(detail['allowed'], {'p1': [], 'p2': []})
        self.assertTrue(any('validation_detail lists illegal references/IDs' in rule
                            for rule in suffix['rules']))

    def test_exhausted_repairs_surface_validation_detail_in_failure_details(self):
        bad = self._bad_reference_feedback()
        with self.assertRaises(ReviewStageError) as caught:
            self.run_responses([self.review, bad, bad])
        details = caught.exception.details
        self.assertEqual(details['stage'], 'novelty_feedback')
        detail = details['validation_detail']
        self.assertEqual(detail['offending'],
                         [{'source_id': 'p1', 'reference_id': 'card:FAKE',
                           'reason': 'unknown_reference_id'}])
        failures = list(self.service.private.glob('review-failure-*.json'))
        self.assertEqual(len(failures), 1)
        recorded = json.loads(failures[0].read_text())
        self.assertEqual(recorded['validation_detail'], detail)

    def test_malformed_json_repair_carries_no_validation_detail(self):
        with self.assertRaises(ReviewStageError) as caught:
            self.run_responses([self.review, {}, {}])
        self.assertNotIn('validation_detail', caught.exception.details)

    def test_persistent_failure_exposes_partial_review_without_gate_receipt(self):
        with self.assertRaises(ReviewStageError) as caught:
            self.run_responses([self.review, {}, {}])
        details = caught.exception.details
        self.assertEqual(details['partial_review']['score'], 0.8)
        self.assertFalse(details['complete_review'])
        self.assertFalse(details['formal_grade'])
        self.assertEqual(self.service.reviews, [])
        self.assertEqual(self.service.grades, [])
        self.assertEqual(len(details['model_calls']), 3)
        failures = list(self.service.private.glob('review-failure-*.json'))
        self.assertEqual(len(failures), 1)
        self.assertEqual(json.loads(failures[0].read_text())['partial_review']['score'], 0.8)

    def test_ready_inconsistency_can_be_repaired_without_inflating_ratings(self):
        bad = copy.deepcopy(self.review)
        bad['candidate_reviews'][0]['verdict'] = 'READY'
        receipt = self.run_responses([bad, self.review, self.feedback])
        self.assertEqual(receipt['review']['score'], 0.8)
        self.assertEqual([x['attempt'] for x in receipt['model_calls']], [1, 2, 1])
        same_initial_prompt = copy.deepcopy(receipt)
        same_initial_prompt['id'] = 'another-fixture-review'
        same_initial_prompt['model_calls'] = [same_initial_prompt['model_calls'][0]]
        # The successful repair saw a different prompt from the initial review;
        # it cannot be evidence of variation under two identical prompts.
        self.assertEqual(score_observations([receipt, same_initial_prompt]), [])

    def test_format_repair_cannot_raise_the_score_to_make_ready_valid(self):
        bad = copy.deepcopy(self.review)
        bad['candidate_reviews'][0]['verdict'] = 'READY'
        inflated = fixture_review(self.scientific, rating=10)
        for item in inflated['candidate_reviews']:
            item['verdict'] = 'READY'
        with self.assertRaisesRegex(ReviewStageError, 'preserve every previously valid numeric rating'):
            self.run_responses([bad, inflated])
        self.assertEqual(self.service.reviews, [])

    def test_exhausted_budget_does_not_make_an_extra_paid_repair(self):
        self.service.tool_calls = self.service.max_tools
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            self.run_responses([{}])
        self.assertEqual(self.model.complete.await_count, 1)
        self.assertEqual(self.service.review_model_calls, 1)
        self.assertEqual(self.service.reviews, [])

    def test_unknown_candidate_and_axis_can_be_removed_by_format_repair(self):
        bad = copy.deepcopy(self.review)
        unknown = copy.deepcopy(bad['candidate_reviews'][0])
        unknown['candidate_id'] = 'NOT_SELECTED'
        bad['candidate_reviews'].append(unknown)
        bad['candidate_reviews'][0]['dimensions']['unknown_axis'] = {'rating': 9}
        receipt = self.run_responses([bad, self.review, self.feedback])
        self.assertEqual(receipt['review']['score'], 0.8)
        self.assertEqual(len(receipt['model_calls']), 3)

    def test_transport_failure_after_schema_failure_keeps_call_history(self):
        self.model = SimpleNamespace(config=SimpleNamespace(model='fixture'),
            last_response_model='fixture', last_usage=None, aclose=AsyncMock(),
            complete=AsyncMock(side_effect=[json.dumps(self.review), '{}', OSError('fixture transport failure')]))
        with patch('sage.autonomous.service.OpenAIModel.from_env', return_value=self.model):
            with self.assertRaises(ReviewStageError) as caught:
                asyncio.run(self.service.judgment(json.dumps(self.primary), 'Fixture'))
        calls = caught.exception.details['model_calls']
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1]['validation'], 'failed')
        self.assertEqual(calls[2]['transport'], 'failed')
        self.assertIsNone(calls[2]['usage'])
        self.assertEqual(caught.exception.details['partial_review']['score'], 0.8)
        self.assertEqual(self.service.reviews, [])

    def test_wall_deadline_between_stages_keeps_the_valid_numeric_assessment(self):
        self.service.deadline = time.time() + 5
        async def complete(stage, prompt, **kwargs):
            self.service.deadline = time.time() - 1
            return json.dumps(self.review)
        model = SimpleNamespace(config=SimpleNamespace(model='fixture'), last_response_model='fixture',
                                last_usage=None, complete=AsyncMock(side_effect=complete), aclose=AsyncMock())
        with patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model):
            with self.assertRaises(ReviewStageError) as caught:
                asyncio.run(self.service.judgment(json.dumps(self.primary), 'Fixture'))
        self.assertEqual(caught.exception.details['stage'], 'novelty_feedback')
        self.assertEqual(caught.exception.details['partial_review']['score'], 0.8)
        self.assertEqual(model.complete.await_count, 1)
        self.assertEqual(self.service.reviews, [])


if __name__ == '__main__':
    unittest.main()
