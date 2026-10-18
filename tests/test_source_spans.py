import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from sage.config import RunConfig
from sage.runtime import Runtime
from sage.fixtures import FixtureSource
from sage.types import Paper
from sage.errors import InvalidResponse, ValidationError
from sage.literature.spans import source_spans, validate_span_claims, extract_span_capsule
from sage.autonomous.service import ResearchService


class SourceSpanTests(unittest.TestCase):
    def test_offsets_reconstruct_exact_unicode_and_math_source(self):
        text = ('The coefficient is exp(-beta*d). 数学条件：β > 0. ' * 50)
        spans = source_spans({'text': text})
        self.assertEqual(''.join(s['text'] for s in spans), text)
        for span in spans:
            self.assertEqual(text[span['start']:span['end']], span['text'])
            self.assertLessEqual(len(span['text']), 480)

    def test_foreign_id_and_model_authored_quote_are_rejected(self):
        spans = source_spans({'text': 'Actual source text.'})
        value = {'claims': [{'category':'method','claim':'A statement','span_ids':['invented']}], 'inferences':[]}
        with self.assertRaises(ValidationError):
            validate_span_claims(json.dumps(value), spans)
        value['claims'][0]['span_ids'] = ['P1']
        value['claims'][0]['quote'] = 'A forged quote'
        with self.assertRaises(InvalidResponse):
            validate_span_claims(json.dumps(value), spans)

    def test_valid_ids_do_not_require_retyping_math(self):
        spans = source_spans({'text': 'Source has \\mathcal{K}(x,y), under assumption A.'})
        raw = json.dumps({'claims':[{'category':'assumptions','claim':'The author assumes A.', 'span_ids':['P1']}], 'inferences':[]})
        self.assertEqual(validate_span_claims(raw, spans)['claims'][0]['span_ids'], ['P1'])

    def test_valid_claims_survive_other_rejected_claims(self):
        spans=source_spans({'text':'Original method text.'})
        value={'claims':[{'category':'method','claim':'A supported description','span_ids':['P1']},
                         {'category':'method','claim':'An unsupported description','span_ids':['fake']}],
               'inferences':[{'inference':'An explicitly unverified interpretation'}]}
        result=validate_span_claims(json.dumps(value),spans)
        self.assertEqual(len(result['claims']),1)
        self.assertEqual(result['rejected_claims'][0]['reason'],'unknown_source_span')
        self.assertEqual(result['inferences'],['An explicitly unverified interpretation'])

    def test_mathematical_conditions_may_reference_more_than_four_spans(self):
        spans=source_spans({'text':'A long original mathematical condition. '*100})
        ids=[s['span_id'] for s in spans]
        self.assertGreater(len(ids),4)
        raw=json.dumps({'claims':[{'category':'assumptions','claim':'A source condition spans several passages.',
                                   'span_ids':ids}],'inferences':[]})
        self.assertEqual(validate_span_claims(raw,spans)['claims'][0]['span_ids'],ids)

    def test_archived_passages_are_immutable_source_lookups(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); service = ResearchService(root/'private', root, 'topic')
            archive = {'paper':{'paper_id':'paper-1'},'source_sha256':'bound-source',
                'source_scope':'supplied_article', 'chunks':[{'chunk_id':'C1','heading':'Methods','text':'Exact original method.'}]}
            service.archive_source(archive)
            self.assertEqual(service.passages('paper-1')['outline'][0]['chunk_id'], 'C1')
            self.assertEqual(service.passages('paper-1',['C1'])['chunks'][0]['text'], 'Exact original method.')
            with self.assertRaises(ValueError): service.passages('paper-1',['invented'])
            with self.assertRaises(ValueError): service.passages('unknown',['C1'])


class SourceSpanAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_section_capsule_keeps_source_conditions_and_scope(self):
        class Model:
            async def complete(self, stage, prompt, *, max_tokens):
                passages = json.loads(prompt.split('INPUT_PASSAGES: ',1)[1])
                return '<capsule>'+json.dumps({'claims':[{'category':'method',
                    'claim':'The author reports a method in this source section '+passages[0]['text'][:20],
                    'span_ids':[passages[0]['span_id']]}], 'inferences':[]})+'</capsule>'
        paper = Paper('paper-1','A paper',abstract='An insufficient abstract',url='https://example.org',
            article={'sections':[{'heading':'Method','text':'Condition A is required. '*80},
                                 {'heading':'Results','text':'A controlled author-reported result. '*70}],
                     'reading_scope':'supplied_text_only'}, evidence_scope='supplied_article')
        config = RunConfig(evidence_mode='capsule',capsule_max_chars=30000)
        rt = Runtime(Model(),Model(),FixtureSource(),config)
        archives=[]
        evidence=await extract_span_capsule(rt,paper,'topic',archive_sink=archives.append)
        self.assertEqual(evidence.capsule['binding'],'original_source_span_ids')
        self.assertEqual(len(evidence.capsule['coverage']['validated_chunk_ids']),2)
        self.assertEqual(evidence.capsule['coverage']['text_extraction_scope'],'supplied_text_only')
        self.assertIsNone(evidence.paper.article)
        self.assertEqual(archives[0]['chunks'][0]['heading'],'Method')
        self.assertTrue(all(ref in evidence.capsule['source_spans'] for c in evidence.capsule['claims'] for ref in c['source_span_ids']))

    async def test_every_critique_retains_verbatim_primary_and_request(self):
        class Model:
            config=SimpleNamespace(model='deepseek-test')
            last_response_model='deepseek-test'
            last_usage={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}
            async def complete(self, stage, prompt, *, max_tokens):
                return json.dumps({'score':0.2,'issues':[],'surviving_ids':[],'summary':'Requires work'})
            async def aclose(self): pass
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);service=ResearchService(root/'private',root,'topic')
            raw='{"candidates": []}\n'
            with patch('sage.autonomous.service.OpenAIModel.from_env',return_value=Model()):
                first=await service.judgment(raw,'method')
                second=await service.judgment(raw,'method')
            self.assertNotEqual(first['request_file'],second['request_file'])
            saved=json.loads((service.private/first['request_file']).read_text(encoding='utf-8'))
            self.assertEqual(saved['primary_raw'],raw)
            self.assertIn(raw,saved['prompt'])
            self.assertFalse(first['independent_acceptance'])
