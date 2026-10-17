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
        queries, papers = [], []
        try:
            limit = self.runtime.config.max_queries
            response = await self.runtime.ask('review.novelty_queries', get_deep_check_idea_novel_search_query_prompt(idea, topic),
                                              ('queries',), validate=lambda r: string_list(r['queries'], limit))
            queries = string_list(response['queries'], limit)
            seen = set()
            for query in queries:
                found = await self.discovery.search(query, limit=5, exclude=seen)
                papers.extend(found)
                seen.update(x for p in found for x in (p.paper_id, p.title.casefold()))
            if not papers:
                self.runtime.event('review.novelty', 'not_established', reason='empty_retrieval')
                return NoveltyAssessment('not_established', queries, [], 'No comparison evidence was retrieved; novelty is unknown.')
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
