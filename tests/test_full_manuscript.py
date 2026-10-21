"""Manuscript handoff, adversarial markup and full-document behavior."""
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

from sage.errors import ConfigurationError, InvalidResponse
from sage.writing.manuscript import parse_chapter, prose_to_latex, render_manuscript, validate_bundle


class ManuscriptTests(unittest.TestCase):
    def test_long_multi_paragraph_sections_are_preserved(self):
        body = ('A substantive mechanism paragraph with supporting evidence. ' * 100 + '\n\n') * 4
        result = parse_chapter(json.dumps({'markdown':body,'evidence_ids':['measurement']}),set(),{'measurement'})
        self.assertGreater(len(result['markdown']),1400)
        self.assertEqual(result['markdown'],body.strip())

    def test_citations_and_evidence_cannot_escape_the_bundle(self):
        for text, ids in [('Supported prose '*50+' [@invented]',[]),('Supported prose '*50,['invented'])]:
            with self.assertRaises(InvalidResponse):
                parse_chapter(json.dumps({'markdown':text,'evidence_ids':ids}),{'real'},{'measurement'})

    def test_model_cannot_add_tex_file_commands(self):
        for command in (r'\input{secret}',r'\write18{command}',r'\begin{filecontents}{newfile}',r'\include{other}'):
            with self.assertRaises(InvalidResponse):
                parse_chapter(json.dumps({'markdown':'Actual manuscript prose '*50+command,'evidence_ids':[]}),set(),set())

    def test_standard_math_symbols_are_not_mistaken_for_file_commands(self):
        body='A finite grid is distinct from a proof of equivalence. '*30+r'$a \nRightarrow b$, $a \nleftrightarrow b$, and $x \varepsilon$.'
        parsed=parse_chapter({'markdown':body,'evidence_ids':[]},set(),set())
        self.assertEqual(parsed['markdown'],body)

    def test_renderer_preserves_math_and_citations_and_escapes_text(self):
        value=prose_to_latex('### Gate\n\nA 95% interval for $R^2$ uses [@real; @second].\n\n$$a_b \\leq \\epsilon$$')
        self.assertIn(r'\subsection{Gate}',value)
        self.assertIn(r'95\%',value)
        self.assertIn('$R^2$',value)
        self.assertIn(r'\citep{real,second}',value)
        self.assertIn(r'\[a_b \leq \epsilon\]',value)

    def test_asset_traversal_rejected(self):
        report={'title':'A paper','chapters':[{'section_id':'methods','title':'Methods','markdown':'A section.'}]}
        bundle={'references':[],'assets':{'methods':[{'path':'../secret.tex'}]}}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigurationError):render_manuscript(report,bundle,directory)

    def test_bibliographic_records_need_reading_scope(self):
        bundle={'schema_version':'sage.manuscript_evidence.v1','evidence':{'data':{}},
                'references':[{'key':'real','title':'A source','url':'https://example.org','bibtex':'@misc{real}'}]}
        with self.assertRaises(ConfigurationError):validate_bundle(bundle)




class WholeManuscriptRegression(unittest.IsolatedAsyncioTestCase):
    async def test_whole_document_mode_preserves_all_sections_and_reviews_them_together(self):
        from sage.writing.manuscript import generate_manuscript, PLAN
        class Runtime:
            config=SimpleNamespace(refinement_rounds=0)
            usage={}
            requests=[]
            async def ask(self,stage,prompt,required,**kwargs):
                self.requests.append((stage,prompt))
                if 'review' in stage:
                    value={'review':json.dumps({'score':6,'issues':[], 'unresolved_research_gaps':[]})}
                else:
                    value={key:(title+' measured interpretation and explicit mechanism. ')*100 for key,title,_ in PLAN}
                    value['sources']=json.dumps({key:['measurement'] for key,_,_ in PLAN})
                kwargs['validate'](value)
                return value
        runtime=Runtime()
        result=await generate_manuscript(runtime,{'schema_version':'sage.manuscript_evidence.v1',
            'title':'Synthetic software test','evidence':{'measurement':{'fixture':True}},'references':[]})
        self.assertEqual(result['completeness'],'full_draft')
        self.assertEqual(len(result['chapters']),len(PLAN))
        self.assertEqual(len([s for s,_ in runtime.requests if '.document.draft' in s]),1)
        for stage,prompt in runtime.requests:
            if '.review.' in stage:
                self.assertIn('Reproducibility and Supplementary Details measured interpretation',prompt)
                self.assertIn('Abstract measured interpretation',prompt)

    async def test_short_output_is_not_silently_called_a_full_paper(self):
        from sage.writing.manuscript import generate_manuscript
        class Runtime:
            config=SimpleNamespace(refinement_rounds=0)
            usage={}
            requests=[]
            async def ask(self,stage,prompt,required,**kwargs):
                self.requests.append((stage,prompt))
                if 'review' in stage:
                    value={'review':json.dumps({'score':4,'issues':[],
                        'unresolved_research_gaps':['No real experiments in this synthetic software test.']})}
                else:
                    value={'prose':'Recorded measurement and methodological interpretation. '*30,
                           'sources':'["measurement"]'}
                kwargs['validate'](value)
                return value
        bundle={'schema_version':'sage.manuscript_evidence.v1','title':'Synthetic software test',
                'evidence':{'measurement':{'fixture':True}},'references':[], 'drafting_mode':'sections'}
        runtime=Runtime();result=await generate_manuscript(runtime,bundle)
        self.assertEqual(result['completeness'],'underdeveloped')
        self.assertTrue(any('.develop.' in s for s,_ in runtime.requests))
        reviews=[p for s,p in runtime.requests if '.review.' in s]
        self.assertEqual(len(reviews),3)
        self.assertTrue(all('Recorded measurement and methodological interpretation.' in p for p in reviews))
        self.assertEqual(result['scientific_acceptance'],'not_assessed')
        self.assertEqual(result['readiness'], 'requires_scientific_revision')
        self.assertEqual(result['unresolved_research_gaps'],
                         ['No real experiments in this synthetic software test.'])

    async def run_gap_case(self, gaps, *, mode='document', rounds=1):
        from sage.writing.manuscript import generate_manuscript, PLAN
        class Runtime:
            config = SimpleNamespace(refinement_rounds=rounds)
            usage = {}
            def __init__(self): self.requests = []
            async def ask(self, stage, prompt, required, **kwargs):
                self.requests.append((stage, prompt))
                if '.review.' in stage:
                    # Later review silence is not evidence of new experiments.
                    found = gaps if '.review.0.' in stage else []
                    value = {'review': json.dumps({'score': 9, 'issues': [],
                                                   'unresolved_research_gaps': found})}
                elif mode == 'document':
                    value = {key: (title + ' recorded interpretation and mechanism. ') * 100
                             for key, title, _ in PLAN}
                    value['sources'] = json.dumps({key: ['measurement'] for key, _, _ in PLAN})
                else:
                    value = {'prose': 'Recorded measurement with explicit mechanism and uncertainty. ' * 100,
                             'sources': '["measurement"]'}
                kwargs['validate'](value)
                return value
        runtime = Runtime()
        result = await generate_manuscript(runtime, {
            'schema_version': 'sage.manuscript_evidence.v1', 'title': 'Synthetic gap regression',
            'evidence': {'measurement': {'fixture': True}}, 'references': [], 'drafting_mode': mode})
        return result, runtime.requests

    async def test_research_gap_without_editorial_issues_is_revised_but_not_erased(self):
        gap = 'No external baseline was measured on the confirmation tasks.'
        result, requests = await self.run_gap_case(['  ' + gap + '  ', gap])
        self.assertEqual(result['unresolved_research_gaps'], [gap])
        self.assertEqual(result['readiness'], 'requires_scientific_revision')
        self.assertEqual(len(result['revision_history']), 1)
        self.assertEqual(len(result['reviews']), 2)
        self.assertTrue(all(not r['unresolved_research_gaps'] for r in result['reviews'][-1]['panel']))
        revision = next(prompt for stage, prompt in requests if '.document.revise.' in stage)
        self.assertIn(gap, revision)
        self.assertIn('do not fabricate measurements', revision)
        self.assertIn('Writing cannot supply this research', revision)
        self.assertEqual(result['scientific_acceptance'], 'not_assessed')

    async def test_section_mode_discloses_gap_without_requesting_new_results(self):
        gap = 'Independent samples are missing for the primary effect estimate.'
        result, requests = await self.run_gap_case([gap], mode='sections')
        revised = [(stage, prompt) for stage, prompt in requests if '.revise.' in stage]
        self.assertEqual([stage for stage, _ in revised], ['manuscript.revise.0.limitations'])
        self.assertIn(gap, revised[0][1])
        self.assertIn('do not fabricate measurements', revised[0][1])
        self.assertEqual(result['unresolved_research_gaps'], [gap])
        self.assertEqual(result['readiness'], 'requires_scientific_revision')

    async def test_research_gap_items_have_an_explicit_text_contract(self):
        for gap in ('', '  ', None, 3, {}, ['missing evidence']):
            with self.subTest(gap=gap), self.assertRaisesRegex(InvalidResponse, 'nonempty plain-text'):
                await self.run_gap_case([gap], rounds=0)

    async def test_clean_review_preserves_existing_external_review_status(self):
        result, requests = await self.run_gap_case([])
        self.assertEqual(result['unresolved_research_gaps'], [])
        self.assertEqual(result['readiness'], 'requires_author_and_external_review')
        self.assertFalse(any('.revise.' in stage for stage, _ in requests))


if __name__=='__main__':unittest.main()
