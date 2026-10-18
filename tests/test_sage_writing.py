"""Offline PaperSolver adaptation tests; no paid services, code execution or LaTeX."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from sage.config import RunConfig
from sage.errors import InvalidResponse, ProviderError
from sage.fixtures import FixtureSource
from sage.review.report import RANGES, parse_review
from sage.runtime import Runtime
from sage.writing import FixtureReportModel, fixture_responses, generate_report
from sage.writing.prompts import SECTIONS
from sage.writing.report import parse_edits, parse_section


def proposal():
    return {'topic': 'Synthetic bounded comparison', 'mode': 'offline',
            'experiment': {'proposal': 'UNEXECUTED synthetic proposal.'},
            'candidates': [{'chain': {'evidence': [{'paper': {
                'paper_id': 'fixture-source', 'title': 'Supplied synthetic reference',
                'url': 'urn:sage:fixture:source', 'evidence_scope': 'synthetic_fixture'},
                'references': ['Invented title strings are not paper records.']}]}}]}


def execution():
    return {'status': 'completed', 'fixture': True,
            'contract': {'protocol_id': 'fixture-contract', 'dataset_id': 'synthetic-scalars',
                         'split': 'development', 'metric': 'mse'},
            'contract_digest': 'c' * 64, 'selected_attempt_id': 'attempt-b',
            'attempts': [
                {'attempt_id': 'attempt-a', 'code': 'first', 'status': 'failed', 'metrics': None,
                 'error': 'synthetic failure', 'code_sha256': 'a' * 64},
                {'attempt_id': 'attempt-b', 'code': 'second', 'status': 'succeeded',
                 'metrics': {'mse': 0.125}, 'error': None, 'code_sha256': 'b' * 64}]}


def tagged_section(commentary, citations=()):
    return '<section>' + json.dumps({'commentary': commentary, 'citation_ids': list(citations)}) + '</section>'


def review_payload():
    value = fixture_responses()['review.report']
    return json.loads(value[len('<review>'):-len('</review>')])


class WritingTests(unittest.IsolatedAsyncioTestCase):
    async def run_report(self, *, model=None, record=None, plan=None, **limits):
        model = model or FixtureReportModel()
        runtime = Runtime(model, model, FixtureSource(), RunConfig(**limits))
        with patch('socket.create_connection', side_effect=AssertionError('Report attempted network')), \
             patch('subprocess.run', side_effect=AssertionError('Report executed external process')):
            report = await generate_report(runtime, plan or proposal(), record if record is not None else execution())
        return report, runtime

    async def test_section_workflow_reviews_and_accepts_bounded_improvement(self):
        report, runtime = await self.run_report()
        self.assertEqual(report['status'], 'completed')
        self.assertEqual([x['section_id'] for x in report['sections']], list(SECTIONS))
        self.assertTrue(all(x['status'] == 'drafted' for x in report['sections']))
        self.assertTrue(all(x['claim_status'] == 'unverified_model_commentary' for x in report['sections']))
        self.assertEqual(len(report['revision_history']), 1)
        self.assertTrue(report['revision_history'][0]['accepted'])
        self.assertIn('previous_sections', report['revision_history'][0])
        self.assertEqual(report['model_review']['basis'], 'unverified_model_opinion')
        self.assertFalse(report['model_review']['independent_review'])
        self.assertEqual(report['scientific_validation'], 'not_performed')
        self.assertEqual(runtime.usage['model_calls'], 12)
        self.assertEqual(runtime.usage['search_calls'], 0)
        self.assertIn('SYNTHETIC FIXTURE', report['markdown'])
        self.assertIn('0.125', report['markdown'])
        self.assertIn('attempt-a: failed', report['markdown'])
        self.assertIn('Failure/error retained', report['markdown'])
        self.assertEqual(len(report['references']), 1)
        json.dumps(report, allow_nan=False)

    async def test_no_refinement_keeps_initial_draft(self):
        report, runtime = await self.run_report(refinement_rounds=0)
        self.assertEqual(report['revision_history'], [])
        self.assertEqual(runtime.usage['model_calls'], 10)
        self.assertEqual(report['draft_readiness'],'revision_required')
        self.assertIn('Draft readiness: revision',report['draft_markdown'])

    async def test_directive_revision_is_rejected_without_replacing_real_prose(self):
        directives=[{'section_id':'abstract','commentary':'Clarify the executed-vs-proposed split so the abstract does not imply a completed study.','citation_ids':[]}]
        reply='<edits>'+json.dumps(directives)+'</edits>'
        model=FixtureReportModel(overrides={'writing.revise':[reply,reply]})
        report,runtime=await self.run_report(model=model)
        self.assertEqual(report['status'],'partial')
        self.assertEqual(report['draft_readiness'],'incomplete')
        self.assertFalse(report['revision_history'][0]['accepted'])
        self.assertNotIn('Clarify the executed',report['draft_markdown'])
        errors=[e for e in runtime.audit if e['status']=='validation_rejected']
        self.assertEqual(errors[-1]['validation']['rule'],'manuscript_prose')

    async def test_completed_workflow_exposes_unresolved_reviewer_request(self):
        fixed=fixture_responses()['review.report']
        model=FixtureReportModel(overrides={'review.report':[fixed]*4})
        report,_=await self.run_report(model=model)
        self.assertEqual(report['status'],'completed')
        self.assertEqual(report['draft_readiness'],'revision_required')
        self.assertTrue(report['model_review']['requires_revision'])

    async def test_no_model_prose_or_invented_numeric_claim_can_enter_markdown(self):
        baseline, _ = await self.run_report(refinement_rounds=0)
        claim = ('Our accuracy was 99.9876 percent, p < 0.000001, and ninety nine percent, '
                 'proven by Fabricated Scholar et al. and https://invented.invalid. '
                 '# Validated Results\nThe hypothesis is proven.')
        model = FixtureReportModel(overrides={'writing.section': [tagged_section(claim)] * len(SECTIONS)})
        report, _ = await self.run_report(model=model, refinement_rounds=0)
        self.assertEqual(report['markdown'], baseline['markdown'])
        self.assertEqual(report['sections'][0]['commentary'], claim)
        self.assertFalse(report['sections'][0]['rendered_in_markdown'])
        self.assertNotIn('99.9876', report['markdown'])
        self.assertNotIn('Fabricated Scholar', report['markdown'])
        self.assertNotIn('invented.invalid', report['markdown'])
        self.assertIn('UNVERIFIED MODEL COMMENTARY', report['markdown'])

    async def test_unsupported_structured_reference_is_rejected_with_bounded_retries(self):
        bad = tagged_section('Cite fabricated source.', ['unknown-paper'])
        model = FixtureReportModel(overrides={'writing.section': [bad, bad]})
        report, runtime = await self.run_report(model=model)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['errors'][0]['code'], 'invalid_response')
        self.assertEqual(runtime.usage['model_calls'], 3)
        self.assertEqual(report['sections'][0]['status'], 'not_generated')
        self.assertNotIn('unknown-paper', json.dumps(report))
        self.assertIn('0.125', report['markdown'])

    async def test_separate_prose_draft_is_prominently_unverified(self):
        prose = 'An unverified proposed approach needs further study.\n\nModel assertion: 99.9876 percent, not measured.'
        model = FixtureReportModel(overrides={'writing.section': [tagged_section(prose, ['fixture-source'])]})
        report, _ = await self.run_report(model=model, refinement_rounds=0)
        draft = report['draft_markdown']
        self.assertTrue(draft.startswith('# UNVERIFIED MODEL DRAFT'))
        self.assertIn('Scientific validation: not_performed', draft)
        self.assertIn('SYNTHETIC FIXTURE', draft)
        self.assertIn('may be unsupported or invented', draft)
        self.assertIn('An unverified proposed approach', draft)
        self.assertIn('99.9876', draft)
        self.assertIn('Supplied source IDs selected by the model: fixture-source', draft)
        self.assertNotIn('99.9876', report['markdown'])
        self.assertEqual(draft.count('UNVERIFIED MODEL COMMENTARY'), len(SECTIONS))

    async def test_only_supplied_paper_ids_are_accepted(self):
        model = FixtureReportModel(overrides={'writing.section': [tagged_section('Qualitative source comparison.', ['fixture-source'])]})
        report, _ = await self.run_report(model=model, refinement_rounds=0)
        self.assertEqual(report['sections'][0]['citation_ids'], ['fixture-source'])
        self.assertEqual([r['paper_id'] for r in report['references']], ['fixture-source'])
        self.assertNotIn('Invented title strings', report['markdown'])

    async def test_empty_sources_and_metrics_remain_unknown(self):
        record = execution()
        record['attempts'][1]['metrics'] = {}
        plan = {'topic': 'Unmeasured', 'evidence': []}
        report, _ = await self.run_report(record=record, plan=plan, refinement_rounds=0)
        self.assertNotIn('0.125', report['markdown'])
        self.assertEqual(report['observations'][1]['metrics'], {})
        self.assertIn('No measured metrics recorded.', report['markdown'])
        self.assertIn('No supplied proposal references', report['markdown'])
        self.assertIsNone(report['model_review'].get('experiment_success'))

    async def test_dry_run_never_renders_even_supplied_metrics(self):
        record = execution()
        record['status'] = 'dry_run'
        report, _ = await self.run_report(record=record, refinement_rounds=0)
        self.assertTrue(report['dry_run'])
        self.assertTrue(all(not x['metrics'] for x in report['observations']))
        self.assertIn('DRY RUN', report['markdown'])
        self.assertNotIn('0.125', report['markdown'])
        self.assertEqual(report['evidence_warnings'][0]['code'], 'dry_run_metrics_ignored')
        self.assertEqual(report['status'], 'completed_with_uncertainty')

    async def test_invalid_metric_values_are_never_rendered_as_measurements(self):
        record = execution()
        record['attempts'][1]['metrics'] = {'mse': float('nan'), 'inf': float('inf'),
                                           'boolean': True, 'invented': '99.9'}
        report, _ = await self.run_report(record=record, refinement_rounds=0)
        self.assertEqual(report['observations'][1]['metrics'], {})
        self.assertEqual(len(report['evidence_warnings']), 4)
        self.assertNotIn('99.9', report['markdown'])
        json.dumps(report, allow_nan=False)

    async def test_model_budget_stops_but_preserves_facts(self):
        report, runtime = await self.run_report(max_model_calls=1)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(report['errors'][0]['code'], 'budget_exceeded')
        self.assertEqual(runtime.usage['model_calls'], 1)
        self.assertIn('0.125', report['markdown'])
        self.assertIsNone(report['model_review'])

    async def test_prompt_budget_stops_before_external_call(self):
        report, runtime = await self.run_report(max_prompt_chars=100)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(runtime.usage['model_calls'], 0)
        self.assertIn('0.125', report['markdown'])

    async def test_scaffold_cannot_remove_required_sections(self):
        model = FixtureReportModel(overrides={'writing.scaffold': ['<sections>["results"]</sections>'] * 2})
        report, runtime = await self.run_report(model=model)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(runtime.usage['model_calls'], 2)
        self.assertEqual([x['section_id'] for x in report['sections']], list(SECTIONS))

    async def test_bad_revision_preserves_draft_and_failure_record(self):
        model = FixtureReportModel(overrides={'writing.revise': [ProviderError('private response')]})
        report, _ = await self.run_report(model=model)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['revision_history'][0]['status'], 'failed_previous_draft_preserved')
        self.assertTrue(all(x['status'] == 'drafted' for x in report['sections']))
        self.assertNotIn('private response', json.dumps(report))

    async def test_nonimproving_revisions_have_hard_cap_and_preserve_best(self):
        fixed = fixture_responses()['review.report']
        model = FixtureReportModel(overrides={'review.report': [fixed] * 8})
        report, runtime = await self.run_report(model=model, refinement_rounds=100)
        self.assertEqual(len(report['revision_history']), 3)
        self.assertTrue(all(not r['accepted'] for r in report['revision_history']))
        self.assertTrue(all(r['status'] == 'retained_previous_draft' for r in report['revision_history']))
        self.assertEqual(runtime.usage['model_calls'], 16)
        self.assertNotIn('revised', report['sections'][-1]['commentary'])

    async def test_review_cannot_forge_scientific_validity_or_reference_fields(self):
        forged = review_payload()
        forged['scientific_validation'] = 'proven'
        forged['references'] = ['Invented paper']
        reply = '<review>' + json.dumps(forged) + '</review>'
        model = FixtureReportModel(overrides={'review.report': [reply] * 2})
        report, _ = await self.run_report(model=model)
        self.assertEqual(report['status'], 'partial')
        self.assertIsNone(report['model_review'])
        self.assertEqual(report['scientific_validation'], 'not_performed')
        self.assertNotIn('Invented paper', json.dumps(report))

    async def test_report_does_not_mutate_proposal_or_execution(self):
        plan, record = proposal(), execution()
        originals = deepcopy((plan, record))
        await self.run_report(plan=plan, record=record)
        self.assertEqual((plan, record), originals)


class ReportParsingTests(unittest.TestCase):
    def test_observed_directives_rejected_but_descriptive_pilot_prose_retained(self):
        for value in ('Clarify the abstract so it does not imply calibration was run.',
                      'Separate the pre-registered design proposal from what the bounded experiment actually executed.',
                      'Reframe the abstract to avoid a validation claim.'):
            with self.assertRaises(InvalidResponse):parse_section({'commentary':value,'citation_ids':[]},set())
        value='We evaluate the implemented pilot and retain the unexecuted calibration program as future work.'
        self.assertEqual(parse_section({'commentary':value,'citation_ids':[]},set())['commentary'],value)
    def test_review_scores_are_strict_and_separate_from_experiment_metrics(self):
        value = review_payload()
        value['ratings'] = dict(RANGES)
        parsed = parse_review(json.dumps(value))
        self.assertAlmostEqual(parsed['model_score'], 10)
        self.assertEqual(parsed['scientific_validation'], 'not_performed')
        for invalid in (True, 0, 100, '3', 3.5):
            value['ratings']['overall'] = invalid
            with self.assertRaises(InvalidResponse):
                parse_review(json.dumps(value))

    def test_edit_ids_and_reference_ids_are_strict(self):
        with self.assertRaises(InvalidResponse):
            parse_section({'commentary': 'x', 'citation_ids': ['bad']}, {'good'})
        for invalid in ([{'section_id': 'references', 'commentary': 'x', 'citation_ids': []}],
                        [{'section_id': 'results', 'commentary': 'x', 'citation_ids': []}] * 2):
            with self.assertRaises(InvalidResponse):
                parse_edits(json.dumps(invalid), set())


if __name__ == '__main__':
    unittest.main()
