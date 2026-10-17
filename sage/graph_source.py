"""arXiv discovery plus real Semantic Scholar citation/reference edges.

No paper-title similarity is labeled a graph edge. The controller may explicitly
fall back to a separately labeled topic_time chain if graph retrieval fails.
"""
from dataclasses import replace
import re
from urllib.parse import quote
from .arxiv import ArxivSource
from .providers import SemanticScholarSource, _PAPER_FIELDS
from .literature.reader import arxiv_identity


class ArxivGraphSource:
    chain_relation = 'citation_reference'
    query_instructions = ArxivSource.query_instructions
    prompt_policy = ('Search metadata is abstract-only. Citation/reference edges, if retrieved, '
                     'are supplied by Semantic Scholar. Obey capsule reading scope and actual chain relation. ')

    def __init__(self, search, graph):
        self.search_source, self.graph_source = search, graph

    @classmethod
    def from_env(cls, *, env=None, **kwargs):
        return cls(ArxivSource.from_env(env=env, **kwargs), SemanticScholarSource.from_env(env=env, **kwargs))

    async def search(self, query, **kwargs):
        return await self.search_source.search(query, **kwargs)

    def relax_queries(self, query):
        return self.search_source.relax_queries(query)

    async def topic_related(self, paper, **kwargs):
        return await self.search_source.topic_related(paper, **kwargs)

    async def related(self, paper, *, direction, limit):
        graph = self.graph_source
        graph._limit(limit)
        if direction not in ('citations', 'references'):
            from .errors import ConfigurationError
            raise ConfigurationError('Graph direction must be citations or references')
        identity = arxiv_identity(paper)
        paper_id = 'ARXIV:' + re.sub(r'v\d+$', '', identity) if identity else paper.paper_id
        data = await graph._request('/paper/' + quote(paper_id, safe='') + '/' + direction,
            {'limit': limit, 'fields': _PAPER_FIELDS + ',externalIds'})
        nested = 'citingPaper' if direction == 'citations' else 'citedPaper'
        papers = graph._papers(data['data'], limit=limit, nested=nested)
        external = {r[nested].get('paperId'): r[nested].get('externalIds') or {}
                    for r in data['data'][:limit] if isinstance(r, dict) and isinstance(r.get(nested), dict)}
        result = []
        for p in papers:
            aid = external.get(p.paper_id, {}).get('ArXiv')
            probe = replace(p, paper_id='arxiv:' + aid) if isinstance(aid, str) else p
            aid = arxiv_identity(probe)
            if aid:
                p = replace(p, paper_id='arxiv:' + aid, url='https://arxiv.org/abs/' + aid,
                            source_provider='semantic_scholar_graph')
            result.append(p)
        return result
