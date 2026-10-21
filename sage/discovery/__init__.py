# Derived from CoI-Agent agents.py and searcher/sementic_search.py, Apache-2.0.
# MODIFIED for SAGE 2026-10-17: injected retrieval, bounded rewrites, safe ranking.
# Source and modification map: NOTICE.md and docs/sage-migration.md.
"""Query expansion, citation retrieval, deduplication and optional vector ranking."""
from __future__ import annotations
from dataclasses import replace
import math
import re
import json
from ..runtime import string_list
from ..errors import InvalidResponse, TransientProviderError, ValidationError
from ..types import Paper, paper_record
from ..dates import within_window
from .prompts import get_deep_search_query_prompt, get_deep_rewrite_query_prompt
from ..literature.prompts import get_deep_judge_relevant_prompt


def cosine(left, right):
    if len(left) != len(right) or not left:
        raise InvalidResponse('Embedding shape mismatch')
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in [*left, *right]):
        raise InvalidResponse('Embedding contains invalid value')
    # Scale before norm computation to avoid overflow for large finite vectors.
    left_scale = max(abs(x) for x in left)
    right_scale = max(abs(x) for x in right)
    if not left_scale or not right_scale:
        return 0.0
    left_unit = [x / left_scale for x in left]
    right_unit = [x / right_scale for x in right]
    left_norm, right_norm = math.hypot(*left_unit), math.hypot(*right_unit)
    return max(-1.0, min(1.0, sum((a / left_norm) * (b / right_norm) for a, b in zip(left_unit, right_unit))))



def unique(papers, excluded=()):
    seen = set(excluded)
    result = []
    for paper in papers:
        if not isinstance(paper, Paper) or not paper.paper_id or not paper.title:
            raise InvalidResponse('Paper source returned an invalid paper contract')
        if paper.paper_id in seen or paper.title.casefold() in seen:
            continue
        seen.update((paper.paper_id, paper.title.casefold()))
        result.append(paper)
    return result


class Discovery:
    def __init__(self, runtime, *, articles=None):
        self.runtime = runtime
        self.articles = dict(articles or {})

    def attach_articles(self, papers):
        result = []
        for paper in papers:
            article = self.articles.get(paper.paper_id, self.articles.get(paper.title))
            result.append(replace(paper, article=article, evidence_scope='user_supplied_full_text') if article else paper)
        return result

    async def queries(self, topic):
        limit = self.runtime.config.max_queries
        prompt = get_deep_search_query_prompt(topic=topic)
        prompt += f'\nReturn at most {limit} queries. ' + getattr(self.runtime.source, 'query_instructions', '')
        value = await self.runtime.ask('discovery.queries', prompt, ('queries',),
                                       validate=lambda r: string_list(r['queries'], limit))
        return string_list(value['queries'], limit)

    async def rank(self, papers, query):
        if not papers:
            return []
        model = self.runtime.main_model
        if self.runtime.config.rerank_mode == 'model' or (self.runtime.config.rerank_mode == 'semantic' and
                                                       not getattr(model, 'embedding_enabled', False)):
            # Bounded semantic reranking is available without an embedding service.
            # Scores are model opinions, never calibrated relevance probabilities.
            pool = papers[:30]
            records = [{'paper_id': p.paper_id, 'title': p.title, 'abstract': p.abstract[:1800]} for p in pool]
            allowed = {p.paper_id for p in pool}
            def validate(r):
                try:
                    rows = json.loads(r['ranking'])
                    if (not isinstance(rows, list) or len(rows) != len(pool) or
                        any(not isinstance(x, dict) or set(x) != {'paper_id','score','reason'} for x in rows) or
                        {x['paper_id'] for x in rows} != allowed or
                        any(type(x['score']) is not int or not 0 <= x['score'] <= 4 or
                            not isinstance(x['reason'], str) or not x['reason'] for x in rows)):
                        raise ValueError
                    if any(len(x['reason']) > 1200 for x in rows):
                        raise ValidationError('bounded_ranking_reason', 'reason')
                except (ValueError, TypeError, KeyError):
                    raise InvalidResponse('Semantic ranking requires each supplied ID exactly once with score 0-4') from None
            response = await self.runtime.ask('discovery.semantic_rank',
                'Rank semantic relevance to this research query: ' + query + '\n' +
                'Score 0=unrelated, 1=remote context, 2=related, 3=directly relevant, 4=closest method/task. '
                'Use problem and mechanism, not merely shared words. Cite no new IDs. '
                'Return <ranking>[{"paper_id":"supplied ID","score":3,"reason":"short justification"},...]</ranking>. '
                'Return every supplied ID exactly once; each reason must be at most 180 characters. '
                'Score must be an integer from 0 through 4. INPUT_PAPERS: ' + json.dumps(records),
                ('ranking',), cheap=True, validate=validate)
            rows = json.loads(response['ranking']); scores = {x['paper_id']: x['score'] for x in rows}
            # Narrative length is a presentation concern, not a reason to lose
            # valid IDs/scores or buy another model response. Preserve the full
            # bounded text and project a marked preview; never change the votes.
            from ..checkpoints import digest
            projected=[{**row,'reason':row['reason'][:180],
                        'reason_truncated':len(row['reason'])>180,
                        'full_reason':row['reason'],'full_reason_sha256':digest(row['reason'])} for row in rows]
            self.runtime.event('discovery.ranking', 'semantic_model', ranking=projected,
                               omitted_pool_count=max(0, len(papers)-len(pool)), basis='unverified_model_opinion')
            return sorted((p for p in pool if scores[p.paper_id] > 0), key=lambda p: -scores[p.paper_id])
        if self.runtime.config.rerank_mode != 'lexical' and getattr(model, 'embedding_enabled', False):
            texts = [query] + [f'Title: {p.title}\nAbstract: {p.abstract}' for p in papers]
            if sum(map(len, texts)) > self.runtime.config.max_prompt_chars:
                raise InvalidResponse('Embedding input exceeds configured size')
            async def embed():
                vectors = await model.embed(texts)
                if len(vectors) != len(texts):
                    raise InvalidResponse('Embedding result count mismatch')
                return [cosine(vectors[0], vector) for vector in vectors[1:]]
            scores = await self.runtime.call('model', 'discovery.embedding_rank', embed)
            self.runtime.event('discovery.ranking', 'embedding', paper_count=len(papers))
        else:
            words = set(re.findall(r'\w+', query.casefold()))
            scores = [len(words & set(re.findall(r'\w+', (p.title + ' ' + p.abstract).casefold()))) for p in papers]
            self.runtime.event('discovery.ranking', 'lexical_fallback', paper_count=len(papers))
        return [paper for _, paper in sorted(zip(scores, papers), key=lambda pair: -pair[0])]

    async def search(self, query, *, limit=5, exclude=(), rerank=True):
        if not isinstance(query, str) or not query.strip():
            return []
        async def operation():
            papers = await self.runtime.source.search(query, limit=min(limit * 6, 100),
                                                      publication_date=self.runtime.config.publication_date)
            valid = unique(papers, exclude)
            included = [p for p in valid if within_window(p, self.runtime.config.publication_date)]
            if len(included) < len(valid):
                self.runtime.event("discovery.date_filter", "excluded", count=len(valid) - len(included))
            return included
        papers = await self.runtime.call('search', 'discovery.search', operation, cache_input={'query': query, 'limit': limit, 'exclude': sorted(exclude), 'publication_date': self.runtime.config.publication_date})
        if rerank:
            chosen = self.attach_articles((await self.rank(papers, query))[:limit])
        else:
            # Prior-art screening preserves bounded provider-order candidates;
            # a generator's relevance score must not silently eliminate counter-work.
            chosen = self.attach_articles(papers[:limit])
            self.runtime.event('discovery.rerank','skipped_for_comparison_recall',
                               retained_ids=[p.paper_id for p in chosen], omitted=len(papers)-len(chosen),
                               ordering='provider_order_not_model_preference')
        self.runtime.event("discovery.retrieval", "recorded", query=query, papers=[paper_record(p) for p in chosen])
        return chosen

    async def search_expanded(self, query, *, limit=5, exclude=(), rerank=True):
        """Bounded provider-aware relaxation; every attempt consumes shared budget."""
        attempts = [query]
        relax = getattr(self.runtime.source, 'relax_queries', None)
        if relax:
            attempts += relax(query)[:self.runtime.config.novelty_search_rewrites]
        attempted = []
        for variant in dict.fromkeys(attempts):
            attempted.append(variant)
            papers = await self.search(variant, limit=limit, exclude=exclude, rerank=rerank)
            if papers:
                return papers, attempted
            self.runtime.event('discovery.search_relaxation', 'empty', query=variant,
                               attempt=len(attempted), original_query=query)
        return [], attempted

    async def optional_search(self, query, *, limit=5, exclude=()):
        """Only supplemental review/planning; never discovery anchors or chain gates."""
        try:
            return await self.search(query, limit=limit, exclude=exclude)
        except TransientProviderError:
            if not self.runtime.allow_incomplete_novelty:
                raise
            self.runtime.event('discovery.supplemental', 'unavailable', query=query,
                               retrieval_incomplete=True, result_is_not_successful_search=True)
            return []

    async def topic_related(self, paper, topic, *, exclude=()):
        async def operation():
            papers = await self.runtime.source.topic_related(paper, limit=self.runtime.config.max_related,
                                                            publication_date=self.runtime.config.publication_date)
            return [p for p in unique(papers, exclude) if within_window(p, self.runtime.config.publication_date)]
        papers = await self.runtime.call('search', 'discovery.topic_related', operation, cache_input={'anchor': paper_record(paper), 'limit': self.runtime.config.max_related, 'exclude': sorted(exclude), 'publication_date': self.runtime.config.publication_date})
        chosen = self.attach_articles(await self.rank(papers, f'{topic} {paper.title}'))
        self.runtime.event('discovery.retrieval', 'recorded', anchor_id=paper.paper_id,
                           relation='topic_time', citation_graph_available=False,
                           papers=[paper_record(p) for p in chosen])
        return chosen

    async def related(self, paper, topic, direction, *, exclude=()):
        async def operation():
            papers = await self.runtime.source.related(paper, direction=direction, limit=self.runtime.config.max_related)
            valid = unique(papers, exclude)
            included = [p for p in valid if within_window(p, self.runtime.config.publication_date)]
            if len(included) < len(valid):
                self.runtime.event("discovery.date_filter", "excluded", count=len(valid) - len(included))
            return included
        papers = await self.runtime.call('search', f'discovery.{direction}', operation, cache_input={'anchor': paper_record(paper), 'direction': direction, 'exclude': sorted(exclude), 'limit': self.runtime.config.max_related, 'publication_date': self.runtime.config.publication_date})
        chosen = self.attach_articles(await self.rank(papers, f'{topic} {paper.title} {paper.abstract}'))
        self.runtime.event('discovery.retrieval', 'recorded', anchor_id=paper.paper_id, direction=direction, papers=[paper_record(p) for p in chosen])
        return chosen

    async def anchor_relevant(self, paper, topic):
        def validate(response):
            if response['relevant'] not in ('0', '1'):
                raise InvalidResponse('Anchor relevance must be 0 or 1')
        response = await self.runtime.ask('discovery.anchor_relevance',
            get_deep_judge_relevant_prompt(paper.title, paper.abstract, topic),
            ('relevant',), cheap=True, validate=validate)
        accepted = response['relevant'] == '1'
        self.runtime.event('discovery.anchor', 'accepted' if accepted else 'rejected_irrelevant',
                           paper_id=paper.paper_id, paper_url=paper.url)
        return accepted

    async def anchors(self, topic, *, limit=None):
        limit = self.runtime.config.max_candidates if limit is None else limit
        papers, excluded = [], set()
        for original in await self.queries(topic):
            query, failed = original, []
            for rewrite in range(self.runtime.config.search_rewrites + 1):
                current = await self.search(query, limit=self.runtime.config.max_related, exclude=excluded)
                accepted = False
                for paper in current:
                    excluded.update((paper.paper_id, paper.title.casefold()))
                    if await self.anchor_relevant(paper, topic):
                        papers.append(paper)
                        accepted = True
                        if len(papers) >= limit:
                            return papers
                if accepted:
                    break
                self.runtime.event('discovery.empty_search', 'no_results', rewrite=rewrite)
                failed.append(query)
                if rewrite < self.runtime.config.search_rewrites:
                    prompt = get_deep_rewrite_query_prompt(failed, topic)
                    prompt += '\n' + getattr(self.runtime.source, 'query_instructions', '')
                    response = await self.runtime.ask('discovery.rewrite', prompt, ('query',))
                    query = response['query']
        return papers
