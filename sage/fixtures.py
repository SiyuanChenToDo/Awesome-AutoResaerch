"""Synthetic, deterministic provider fakes. These are NOT real papers or findings.

Only provider responses are simulated. Discovery, chain traversal, parsing,
regeneration, ranking, review, design, budgets and audits are the real pipeline.
"""
from __future__ import annotations
from collections import Counter, deque
import json
from .types import Paper
from .errors import ProviderError


def fixture_papers():
    papers = []
    for family in ('a', 'b'):
        for suffix, year in (('root', 2020), ('prior', 2021), ('anchor', 2022), ('next', 2023)):
            identity = f'fixture-{family}-{suffix}'
            references = [{'ref_id': 'r1', 'title': f'Synthetic {family} prior', 'year': 2021}] if suffix == 'anchor' else []
            papers.append(Paper(identity, f'Synthetic {family} {suffix}',
                                f'Synthetic fixture only: {family} method development, {suffix} stage; no measured result.',
                                year, f'urn:sage:fixture:{identity}', 0,
                                {'sections': [{'heading': 'Synthetic method', 'text': f'Fixture {identity}; proposed controls and limitations, not empirical evidence.'}],
                                 'references': references}, 'synthetic_fixture'))
    papers.append(Paper('fixture-comparison', 'Synthetic comparison evidence', 'Synthetic prior-work comparison fixture.',
                        2024, 'urn:sage:fixture:comparison', evidence_scope='synthetic_fixture'))
    return papers


class FixtureSource:
    def __init__(self, *, empty=False, empty_novelty=False):
        self.papers = {p.paper_id: p for p in fixture_papers()}
        self.calls = []
        self.empty, self.empty_novelty = empty, empty_novelty

    async def search(self, query, *, limit, publication_date=None):
        self.calls.append(('search', query, limit))
        if self.empty:
            return []
        if query in ('sage-fixture-a', 'sage-fixture-b'):
            return [self.papers[f'fixture-{query[-1]}-anchor']]
        if query == 'sage-fixture-novelty':
            return [] if self.empty_novelty else [self.papers['fixture-comparison']]
        matches = [p for p in self.papers.values() if p.title.casefold() == query.casefold()]
        if matches:
            return matches[:limit]
        if query in ('sage-fixture-review', 'sage-fixture-refine'):
            return [self.papers['fixture-a-root'], self.papers['fixture-b-root']][:limit]
        return []

    async def related(self, paper, *, direction, limit):
        self.calls.append((direction, paper.paper_id, limit))
        if self.empty:
            return []
        parts = paper.paper_id.split('-')
        if len(parts) != 3:
            return []
        _, family, suffix = parts
        next_suffix = {'anchor': 'next'}.get(suffix) if direction == 'citations' else {'anchor': 'prior', 'prior': 'root'}.get(suffix)
        return [self.papers[f'fixture-{family}-{next_suffix}']] if next_suffix else []


class FixtureModel:
    embedding_enabled = False

    def __init__(self, *, overrides=None):
        self.calls = Counter()
        self.overrides = {stage: deque(values) for stage, values in (overrides or {}).items()}

    async def complete(self, stage, prompt, *, max_tokens):
        self.calls[stage] += 1
        if self.overrides.get(stage):
            response = self.overrides[stage].popleft()
            if isinstance(response, BaseException):
                raise response
            return response
        if stage.startswith('discussion.'):
            from .discussion.fixtures import respond
            return respond(stage, prompt)
        if stage == 'review.claims.extract':
            papers = json.loads(prompt.split('READ_EVIDENCE: ',1)[1].split('\nExtract ',1)[0])
            return '<claims>' + json.dumps([{'statement':'Synthetic proposed mechanism, not a finding.',
                'kind':'method','source_ids':[papers[0]['paper_id']], 'queries':['sage-fixture-novelty'],
                'falsifier':'A paired synthetic control shows no change.'}]) + '</claims>'
        if stage == 'review.claims.assess':
            dossier = json.loads(prompt.split('CLAIM_DOSSIER: ',1)[1].split('\nIndependently ',1)[0])
            return '<assessment>' + json.dumps({'overall_verdict':'insufficient_evidence',
                'combination_prior_id':None,'score':5,'verdict':'not ready','uncertainty':'Synthetic fixture only.',
                'assessments':[{'claim_id':d['claim']['claim_id'],'status':'insufficient_evidence',
                    'closest_paper_id':d['sources'][0]['paper']['paper_id'] if d['sources'] else None,
                    'overlap':'Synthetic context.','delta':'Unverified proposal.',
                    'evidence_limit':'Fixture is not scientific evidence.','decisive_test':'Run the fixed synthetic comparison.'}
                    for d in dossier]}) + '</assessment>'
        if stage == 'literature.span_capsule':
            passages = json.loads(prompt.split('INPUT_PASSAGES: ', 1)[1])
            return '<capsule>' + json.dumps({'claims': [{'category': 'method',
                'claim': 'Synthetic fixture source text, not empirical evidence.',
                'span_ids': [passages[0]['span_id']]}], 'inferences': []}) + '</capsule>'
        if stage == 'literature.entailment':
            batch = json.loads(prompt.split('INPUT_CLAIMS_AND_ORIGINAL_PASSAGES: ', 1)[1])
            return '<entailment>' + json.dumps({'claims': [{
                'claim_id': item['claim_id'], 'verdict': 'supported',
                'source_span_ids': list(item['source_spans']),
                'reason': 'Deterministic fixture only, not a scientific semantic judgment.',
                'unsupported_details': []} for item in batch]}) + '</entailment>'
        if stage == 'literature.capsule':
            chunk = json.loads(prompt.split('INPUT_CHUNK: ', 1)[1])
            value = {'claims': [{'category': 'method', 'claim': 'Synthetic fixture text, not empirical evidence.',
                                 'quote': chunk['text'][:200], 'chunk_id': chunk['chunk_id']}], 'inferences': []}
            return '<capsule>' + json.dumps(value) + '</capsule>'
        if stage == 'discovery.semantic_rank':
            papers = json.loads(prompt.split('INPUT_PAPERS: ', 1)[1])
            return '<ranking>' + json.dumps([{'paper_id': p['paper_id'], 'score': 3,
                        'reason': 'Synthetic fixture relevance, not calibrated.'} for p in papers]) + '</ranking>'
        if stage == 'review.nearest_work':
            papers = json.loads(prompt.split('RETRIEVED: ', 1)[1])
            identity = papers[0]['paper_id']
            return '<comparison>' + json.dumps({'verdict':'insufficient_evidence','closest_paper_id':identity,
                'comparisons':[{'paper_id':identity,'shared_problem':'Synthetic comparison',
                 'shared_mechanism':'Not established by synthetic evidence','difference':'Unverified proposed difference',
                 'evidence_limit':'Fixture only'}], 'uncertainty':'Fixture does not establish novelty.'}) + '</comparison>'
        if stage == 'discovery.queries':
            return '<queries>["sage-fixture-a", "sage-fixture-b"]</queries>'
        if stage == 'discovery.rewrite':
            return '<query>sage-fixture-a</query>'
        if stage == 'literature.extract':
            identity = prompt.split('Paper ID: ', 1)[1].split('\n', 1)[0]
            refs = f'["Synthetic {identity.split("-")[1]} prior"]' if identity.endswith('anchor') else '[]'
            return (f'<idea>Synthetic source idea for {identity}; unverified.</idea>'
                    f'<experiment>Synthetic source plan for {identity}; not executed.</experiment>'
                    f'<entities>Fixture method, fixed evaluator, controlled budget</entities><references>{refs}</references>')
        if stage in ('literature.relevance', 'discovery.anchor_relevance'):
            return '<relevant>1</relevant>'
        if stage == 'ideation.trend':
            return '<trend>Synthetic chain moves from a baseline toward controlled evaluation.</trend>'
        if stage == 'ideation.entities':
            return '<entities>Fixed evaluator; paired seeds; bounded search budget.</entities>'
        if stage == 'ideation.future':
            return '<future>Test a bounded method against a frozen baseline.</future><human>Compare alternative explanations with controls.</human>'
        if stage == 'ideation.generate':
            return '<method>Propose a controlled synthetic comparison.</method><novelty>Unknown until evidence review.</novelty><motivation>Exercise the workflow honestly.</motivation>'
        if stage == 'ideation.finalize':
            return f'<final_idea>Synthetic proposal {self.calls[stage]}: compare bounded candidates with a frozen evaluator. No experimental result claimed.</final_idea>'
        if stage == 'review.novelty_queries':
            return '<queries>["sage-fixture-novelty"]</queries>'
        if stage == 'review.novelty_compare':
            similar = '1' if self.calls[stage] == 1 else '0'
            return f'<similar>{similar}</similar><summary>Synthetic screening only; global novelty remains unproved.</summary><similar_paper_id>0</similar_paper_id>'
        if stage == 'review.pairwise':
            return ''.join(f'<{name}>2</{name}>' for name in ('novelty', 'relevance', 'significance', 'clarity', 'feasibility', 'effectiveness'))
        if stage == 'review.literature_queries':
            return '<queries>["sage-fixture-review"]</queries>'
        if stage == 'review.literature_suggestions':
            return '<suggestions>Use matched budgets and report failed attempts; synthetic advice.</suggestions>'
        if stage == 'review.experiment':
            return '<suggestion>Freeze evaluation before trials and add paired-seed controls.</suggestion>'
        from .experiment_design.contract import fixture_contract
        plan_tag = '<plan_contract>' + json.dumps(fixture_contract()) + '</plan_contract>'
        if stage == 'experiment_design.generate':
            return '<experiment>UNEXECUTED synthetic plan: freeze data and evaluator; compare baseline and candidate under equal budgets; report all seeds and failures.</experiment>' + plan_tag
        if stage == 'experiment_design.refine_query':
            return '<query>sage-fixture-refine</query>'
        if stage == 'experiment_design.paper_info':
            return '<info>Synthetic evidence recommends matched budgets and explicit failure accounting.</info>'
        if stage == 'experiment_design.refine':
            return '<experiment>UNEXECUTED revised synthetic plan: preregister fixed data/evaluator, paired seeds, equal budgets, negative controls, and all failed attempts. Require human review before execution.</experiment>' + plan_tag
        raise ProviderError('Fixture has no response for requested stage')
