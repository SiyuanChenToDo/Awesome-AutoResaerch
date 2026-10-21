# Derived from CoI-Agent ReviewAgent, check_novel and judge_idea, Apache-2.0.
# MODIFIED for SAGE 2026-10-17: explicit uncertainty, six strict voting dimensions.
# Source and modification map: NOTICE.md and docs/sage-migration.md.
"""Evidence-backed novelty screening and proposal review; never scientific proof."""
from __future__ import annotations
from ..errors import InvalidResponse, TransientProviderError
from ..runtime import string_list
from ..types import NoveltyAssessment, paper_record
from .prompts import (get_deep_check_idea_novel_search_query_prompt, get_deep_check_idea_novel_prompt,
                      get_judge_idea_all_prompt, get_review_search_related_paper_prompt,
                      get_review_suggestions_from_papers_prompt, get_review_experiment_design_suggestions_prompt)

DIMENSIONS = ('novelty', 'relevance', 'significance', 'clarity', 'feasibility', 'effectiveness')


class Review:
    def __init__(self, runtime, discovery):
        self.runtime, self.discovery = runtime, discovery

    async def novelty(self, idea, topic):
        if self.runtime.config.claim_review:
            from .claims import screen_claims
            return await screen_claims(self.runtime, self.discovery, idea, topic)
        queries, papers = [], []
        try:
            limit = self.runtime.config.max_queries
            response = await self.runtime.ask('review.novelty_queries', get_deep_check_idea_novel_search_query_prompt(idea, topic) +
                                               '\n' + getattr(self.runtime.source, 'query_instructions', '') +
                                               '\nSearch problem, mechanism and closest prior methods in separate short queries; do not join all controls into one query.',
                                              ('queries',), validate=lambda r: string_list(r['queries'], limit))
            initial_queries = string_list(response['queries'], limit)
            queries = []
            seen = set()
            for query in initial_queries:
                if self.runtime.config.novelty_search_rewrites:
                    found, attempted = await self.discovery.search_expanded(query, limit=5, exclude=seen)
                    queries.extend(attempted)
                else:
                    found = await self.discovery.search(query, limit=5, exclude=seen)
                    queries.append(query)
                papers.extend(found)
                seen.update(x for p in found for x in (p.paper_id, p.title.casefold()))
            if not papers:
                self.runtime.event('review.novelty', 'not_established', reason='empty_retrieval')
                return NoveltyAssessment('not_established', queries, [], 'No comparison evidence was retrieved; novelty is unknown.')
            if self.runtime.config.evidence_mode == 'capsule':
                return await self.compare_nearest(idea, papers, queries)
            def validate(response):
                if response['similar'] not in ('0', '1'):
                    raise InvalidResponse('Similarity must be 0 or 1')
                if response['similar'] == '1':
                    try:
                        index = int(response['similar_paper_id'])
                    except ValueError:
                        raise InvalidResponse('Similar paper index is invalid') from None
                    if index < 0 or index >= len(papers):
                        raise InvalidResponse('Similar paper index is out of range')
            response = await self.runtime.ask('review.novelty_compare', get_deep_check_idea_novel_prompt(idea, papers),
                                              ('similar', 'summary', 'similar_paper_id'), cheap=True,
                                              allow_empty=('similar_paper_id',), validate=validate)
            similar = response['similar'] == '1'
            return NoveltyAssessment('similar_work_found' if similar else 'no_similar_work_found', queries, papers,
                                     response['summary'], papers[int(response['similar_paper_id'])].paper_id if similar else None)
        except TransientProviderError:
            if not self.runtime.allow_incomplete_novelty:
                raise
            self.runtime.event('review.novelty', 'not_established', reason='provider_screening_incomplete',
                               compared_source_ids=[p.paper_id for p in papers])
            return NoveltyAssessment('not_established', queries, papers,
                'Provider screening unavailable or incomplete; novelty is unknown. No successful fresh search is implied.')
        except InvalidResponse:
            self.runtime.event('review.novelty', 'not_established', reason='invalid_model_output')
            return NoveltyAssessment('not_established', queries, papers, 'Invalid model screening output; novelty is unknown.')

    async def compare_nearest(self, idea, papers, queries):
        """Explicit overlap/difference ledger; abstract screening is never a novelty proof."""
        import json
        retrieved_ids = {p.paper_id for p in papers}
        # The candidate may legitimately cite its seed literature. Supply those
        # exact known cards too, rather than asking the model to compare them and
        # then rejecting their IDs merely because this search did not return them.
        known = getattr(self.runtime, 'evidence_cards', {})
        input_papers = [e.paper for identity,e in known.items() if identity in idea and identity not in retrieved_ids]
        papers = list(papers) + input_papers
        self.runtime.event('review.comparison_corpus','assembled',
                           retrieved_ids=sorted(retrieved_ids), input_evidence_ids=[p.paper_id for p in input_papers])
        allowed = {p.paper_id for p in papers}
        def validate(r):
            try:
                value = json.loads(r['comparison'])
                if set(value) != {'verdict','closest_paper_id','comparisons','uncertainty'}:
                    raise ValueError
                if value['verdict'] not in ('overlap','distinct_within_retrieved','insufficient_evidence'):
                    raise ValueError
                if value['closest_paper_id'] not in allowed or not isinstance(value['uncertainty'], str):
                    raise ValueError
                rows = value['comparisons']
                if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
                    raise ValueError
                if len({x['paper_id'] for x in rows}) != len(rows):
                    raise ValueError
                for row in rows:
                    if set(row) != {'paper_id','shared_problem','shared_mechanism','difference','evidence_limit'} or row['paper_id'] not in allowed:
                        raise ValueError
                    if any(not isinstance(v, str) or not 1 <= len(v) <= 1000 for v in row.values()):
                        raise ValueError
            except (ValueError, TypeError, KeyError):
                raise InvalidResponse('Nearest-work comparison requires valid supplied IDs and explicit differences') from None
        from ..literature import Literature
        literature = Literature(self.runtime, self.discovery)
        for paper in papers[:self.runtime.config.novelty_fulltext_papers]:
            if paper.paper_id not in self.runtime.evidence_cards:
                await literature.extract(paper, 'Closest prior work to proposed idea: ' + idea[:2000])
        records = [{'paper_id':p.paper_id,'title':p.title,'abstract':p.abstract,'scope':p.evidence_scope,
                    'acquisition_basis':'retrieved_this_screen' if p.paper_id in retrieved_ids else 'existing_read_input_evidence',
                    'capsule': self.runtime.evidence_cards[p.paper_id].capsule
                    if p.paper_id in self.runtime.evidence_cards else None} for p in papers]
        response = await self.runtime.ask('review.nearest_work',
            'Compare this proposed idea with its closest retrieved prior work. Do not confuse new wording or '
            'extra controls with a new mechanism. Compare problem, mechanism and claimed contribution. '
            'Obey each source scope: a supplied capsule may include article text; other records are abstract-only. Absence of a detail in an abstract '
            'does not establish that the full paper lacks it; use insufficient_evidence when needed. '
            'Return <comparison>{"verdict":"overlap|distinct_within_retrieved|insufficient_evidence",'
            '"closest_paper_id":"supplied ID","comparisons":[{"paper_id":"supplied ID",'
            '"shared_problem":"...","shared_mechanism":"...","difference":"...","evidence_limit":"..."}],'
            '"uncertainty":"..."}</comparison>. Compare 1-5 closest papers with no invented IDs. '
            'IDEA: ' + idea + '\nRETRIEVED: ' + json.dumps(records, ensure_ascii=False),
            ('comparison',), validate=validate)
        value = json.loads(response['comparison'])
        status = {'overlap':'similar_work_found','distinct_within_retrieved':'no_similar_work_found',
                  'insufficient_evidence':'not_established'}[value['verdict']]
        return NoveltyAssessment(status, queries, papers, value['uncertainty'],
            value['closest_paper_id'] if status == 'similar_work_found' else None,
            basis='model_assessment_of_retrieved_and_supplied_sources', comparisons=value['comparisons'])

    async def rank(self, candidates, topic):
        scores = [0.0] * len(candidates)
        comparisons = []
        def validate(response):
            if any(response[dimension] not in ('0', '1', '2') for dimension in DIMENSIONS):
                raise InvalidResponse('Pairwise judgments must be 0, 1 or 2')
        # Both directions are retained from CoI to expose position sensitivity.
        for i, left in enumerate(candidates):
            for j, right in enumerate(candidates):
                if i == j:
                    continue
                response = await self.runtime.ask('review.pairwise', get_judge_idea_all_prompt(left.idea, right.idea, topic),
                                                  DIMENSIONS, validate=validate)
                votes = {dimension: int(response[dimension]) for dimension in DIMENSIONS}
                for winner in votes.values():
                    scores[i] += 1.0 if winner == 0 else 0.5 if winner == 2 else 0.0
                    scores[j] += 1.0 if winner == 1 else 0.5 if winner == 2 else 0.0
                comparisons.append({'left': i, 'right': j, 'votes': votes})
        selected = max(range(len(candidates)), key=lambda i: (scores[i], -i))
        return {'method': 'ordered_pairwise_votes', 'basis': 'model_preference_only', 'dimensions': list(DIMENSIONS),
                'scores': scores, 'comparisons': comparisons, 'selected_index': selected,
                'scientific_validation': False}

    async def literature_suggestions(self, candidate, topic):
        limit = self.runtime.config.max_queries
        value = await self.runtime.ask('review.literature_queries', get_review_search_related_paper_prompt(candidate.idea, topic),
                                       ('queries',), validate=lambda r: string_list(r['queries'], limit))
        papers, seen = [], set()
        for query in string_list(value['queries'], limit):
            found = await self.discovery.optional_search(query, limit=2, exclude=seen)
            papers.extend(found)
            seen.update(x for p in found for x in (p.paper_id, p.title.casefold()))
        if not papers:
            return {'suggestions': '', 'papers': [], 'status': 'insufficient_evidence'}
        content = '\n'.join(f'{p.paper_id}: {p.title}; {p.abstract}; scope={p.evidence_scope}' for p in papers)
        value = await self.runtime.ask('review.literature_suggestions', get_review_suggestions_from_papers_prompt(candidate.idea, topic, content),
                                       ('suggestions',), allow_empty=('suggestions',))
        return {'suggestions': value['suggestions'], 'papers': [paper_record(p) for p in papers], 'status': 'model_review'}

    async def experiment(self, idea, experiment, entities):
        response = await self.runtime.ask('review.experiment', get_review_experiment_design_suggestions_prompt(idea, experiment, entities),
                                          ('suggestion',), cheap=True)
        return response['suggestion']
