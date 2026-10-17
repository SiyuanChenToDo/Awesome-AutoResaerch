# Derived from CoI-Agent agents.py and searcher/sementic_search.py, Apache-2.0.
# MODIFIED for SAGE 2026-10-17: injected retrieval, bounded rewrites, safe ranking.
# Source and modification map: NOTICE.md and docs/sage-migration.md.
"""Query expansion, citation retrieval, deduplication and optional vector ranking."""
from __future__ import annotations
from dataclasses import replace
import math
import re
from ..runtime import string_list
from ..errors import InvalidResponse
from ..types import Paper, paper_record
from ..dates import within_window
from .prompts import get_deep_search_query_prompt, get_deep_rewrite_query_prompt


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
        value = await self.runtime.ask('discovery.queries', get_deep_search_query_prompt(topic=topic), ('queries',),
                                       validate=lambda r: string_list(r['queries'], limit))
        return string_list(value['queries'], limit)

    async def rank(self, papers, query):
        if not papers:
            return []
        model = self.runtime.main_model
        if getattr(model, 'embedding_enabled', False):
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

    async def search(self, query, *, limit=5, exclude=()):
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
        papers = await self.runtime.call('search', 'discovery.search', operation)
        chosen = self.attach_articles((await self.rank(papers, query))[:limit])
        self.runtime.event("discovery.retrieval", "recorded", query=query, papers=[paper_record(p) for p in chosen])
        return chosen

    async def related(self, paper, topic, direction, *, exclude=()):
        async def operation():
            papers = await self.runtime.source.related(paper, direction=direction, limit=self.runtime.config.max_related)
            valid = unique(papers, exclude)
            included = [p for p in valid if within_window(p, self.runtime.config.publication_date)]
            if len(included) < len(valid):
                self.runtime.event("discovery.date_filter", "excluded", count=len(valid) - len(included))
            return included
        papers = await self.runtime.call('search', f'discovery.{direction}', operation)
        chosen = self.attach_articles(await self.rank(papers, f'{topic} {paper.title} {paper.abstract}'))
        self.runtime.event('discovery.retrieval', 'recorded', anchor_id=paper.paper_id, direction=direction, papers=[paper_record(p) for p in chosen])
        return chosen

    async def anchors(self, topic):
        papers, excluded = [], set()
        for original in await self.queries(topic):
            query, failed = original, []
            for rewrite in range(self.runtime.config.search_rewrites + 1):
                current = await self.search(query, limit=1, exclude=excluded)
                if current:
                    papers.extend(current)
                    excluded.update(x for p in current for x in (p.paper_id, p.title.casefold()))
                    break
                self.runtime.event('discovery.empty_search', 'no_results', rewrite=rewrite)
                failed.append(query)
                if rewrite < self.runtime.config.search_rewrites:
                    response = await self.runtime.ask('discovery.rewrite', get_deep_rewrite_query_prompt(failed, topic), ('query',))
                    query = response['query']
            if len(papers) >= self.runtime.config.max_candidates:
                break
        return papers
