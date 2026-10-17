"""Explicit arXiv Atom metadata provider; no citation graph or PDF retrieval.

API: https://info.arxiv.org/help/api/user-manual.html
Terms: https://info.arxiv.org/help/api/tou.html (single connection, >=3s interval).
The upstream Agent Laboratory tools.py ArxivSearch at d9017d90 uses arxiv.Search;
this is an owned stdlib adapter, not an import/copy of that implementation.
"""
from __future__ import annotations
import asyncio
from datetime import date
from functools import partial
import os
import re
import threading
import time
from urllib.parse import urlencode, urlsplit
import xml.etree.ElementTree as ET

from .dates import publication_window, within_window
from .errors import ConfigurationError, InvalidResponse, ProviderError, TransientProviderError
from .providers import (HTTPResponse, _environment_proxy, _metadata_https_request,
                        _provider_error, _proxy_url, _timeout, SemanticScholarSource)
from .types import Paper

_ATOM = '{http://www.w3.org/2005/Atom}'
_ID = re.compile(r'(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z.\-]+/\d{7})(?:v[1-9]\d*)?')
_LOCK = threading.Lock()
_LAST_FINISHED = 0.0
_STOP = {'a', 'an', 'the', 'and', 'or', 'of', 'for', 'in', 'on', 'to', 'with', 'by', 'using', 'from'}


def _terms(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 4096:
        raise ConfigurationError('arXiv query must contain 1 to 4096 characters')
    terms = list(dict.fromkeys(w.lower() for w in re.findall(r'[^\W_]+', query, re.UNICODE)
                              if w.lower() not in _STOP and len(w) > 1))[:12]
    if not terms:
        raise ConfigurationError('arXiv query has no searchable terms')
    return terms


def _query(query, *, thematic=False):
    # Treat all model text as literal terms, never arbitrary API field syntax.
    return (' OR ' if thematic else ' AND ').join('all:"' + word + '"' for word in _terms(query))


def _paced_request(transport, url, headers, timeout, max_bytes):
    """Process-wide serial pacing, including failures and cancelled async waiters.

    The lock lives in the worker, so cancellation never releases it while network
    IO is still active. Lock/wait time consumes the same request deadline.
    """
    global _LAST_FINISHED
    deadline = time.monotonic() + timeout
    if not _LOCK.acquire(timeout=timeout):
        raise TimeoutError
    try:
        delay = max(0.0, _LAST_FINISHED + 3.0 - time.monotonic())
        if delay >= deadline - time.monotonic():
            raise TimeoutError
        time.sleep(delay)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        try:
            return transport(url, headers, remaining, max_bytes)
        finally:
            _LAST_FINISHED = time.monotonic()
    finally:
        _LOCK.release()


class ArxivSource:
    chain_relation = 'topic_time'

    @staticmethod
    def relax_queries(query):
        terms = _terms(query)
        return list(dict.fromkeys(' '.join(terms[:n]) for n in (4, 2) if len(terms) > n))
    query_instructions = ('For arXiv, each query must contain 2-4 essential topic keywords only. '
                          'Do not put evaluation constraints, full sentences, Boolean operators or API field syntax in queries. '
                          'Use distinct concise queries for distinct aspects of the topic.')
    prompt_policy = ('Source policy: arXiv search returns metadata/abstracts, not verified peer review. '
                     'An attached evidence capsule may include separately retrieved article text; obey its scope and coverage. '
                     'No citation/reference graph is available. Topic/time chains do not establish influence '
                     'or that a later paper builds on an earlier one. Do not infer missing references. '
                     'For search query outputs use concise 2-4 keyword strings, no API syntax.\n\n')

    def __init__(self, *, timeout=20.0, max_response_bytes=2_000_000, proxy_url=None, transport=None):
        self.timeout = _timeout(timeout)
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 10_000_000:
            raise ConfigurationError('Paper response byte limit must be from 1 to 10000000')
        _proxy_url(proxy_url)
        self.max_response_bytes = max_response_bytes
        self._transport = transport or partial(_metadata_https_request, proxy_url=proxy_url)
        self.request_count = 0

    @classmethod
    def from_env(cls, *, env=None, **kwargs):
        env = os.environ if env is None else env
        return cls(proxy_url=_environment_proxy(env), **kwargs)

    async def _search(self, query, *, limit, publication_date=None, thematic=False):
        SemanticScholarSource._limit(limit)
        expression = _query(query, thematic=thematic)
        if publication_date is not None:
            lower, upper = publication_window(publication_date)
            expression = '(' + expression + ') AND submittedDate:[' + lower.strftime('%Y%m%d') + '0000 TO ' + upper.strftime('%Y%m%d') + '2359]'
        url = 'https://export.arxiv.org/api/query?' + urlencode({
            'search_query': expression, 'start': 0, 'max_results': limit,
            'sortBy': 'relevance', 'sortOrder': 'descending'})
        headers = {'Accept': 'application/atom+xml',
                   'User-Agent': 'SAGE-research-workflow/1 (https://github.com/SiyuanChenToDo/Awesome-AutoResaerch)'}
        self.request_count += 1
        try:
            reply = await asyncio.wait_for(asyncio.to_thread(_paced_request, self._transport, url,
                        headers, self.timeout, self.max_response_bytes), timeout=self.timeout)
        except (ConfigurationError, InvalidResponse):
            raise
        except Exception as error:
            raise _provider_error(error, 'arXiv provider') from None
        if not isinstance(reply, HTTPResponse) or type(reply.status) is not int:
            raise InvalidResponse('arXiv provider returned an invalid response')
        if reply.status != 200:
            if reply.status == 429:
                from .errors import RateLimited
                raise RateLimited('arXiv provider rate limited (HTTP 429)', reply.retry_after_seconds)
            if 500 <= reply.status <= 599:
                raise TransientProviderError(f'arXiv provider temporarily unavailable (HTTP {reply.status})')
            raise ProviderError(f'arXiv provider request rejected (HTTP {reply.status})')
        if not isinstance(reply.body, bytes) or len(reply.body) > self.max_response_bytes:
            raise InvalidResponse('arXiv response exceeds byte/type limit')
        return [paper for paper in self.parse(reply.body, limit=limit) if within_window(paper, publication_date)]

    async def search(self, query, *, limit, publication_date=None):
        return await self._search(query, limit=limit, publication_date=publication_date)

    async def topic_related(self, paper, *, limit, publication_date=None):
        # OR over anchor title words is a thematic expansion, never a graph edge.
        return await self._search(paper.title, limit=limit, publication_date=publication_date, thematic=True)

    async def related(self, paper, *, direction, limit):
        raise ConfigurationError('arXiv metadata has no citation/reference graph; use explicit topic/time chains')

    @staticmethod
    def parse(body, *, limit):
        # UTF-8 only, no DTD/entity declarations. Bound before XML parsing.
        if not isinstance(body, bytes) or len(body) > 10_000_000:
            raise InvalidResponse('Invalid arXiv XML size/type')
        try:
            text = body.decode('utf-8')
            if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
                raise ValueError
            feed = ET.fromstring(text)
        except (ValueError, ET.ParseError):
            raise InvalidResponse('arXiv provider returned invalid/unsafe Atom XML') from None
        if feed.tag != _ATOM + 'feed':
            raise InvalidResponse('arXiv provider did not return an Atom feed')
        entries = feed.findall(_ATOM + 'entry')
        if len(entries) > 100:
            raise InvalidResponse('arXiv provider returned too many entries')
        papers, seen = [], set()
        for entry in entries:
            def value(name):
                return ' '.join((entry.findtext(_ATOM + name) or '').split())
            origin = value('id')
            try:
                parts = urlsplit(origin)
                identifier = parts.path.removeprefix('/abs/')
                valid = (parts.scheme in ('http', 'https') and parts.netloc == 'arxiv.org'
                         and parts.path.startswith('/abs/') and not parts.query and not parts.fragment
                         and _ID.fullmatch(identifier))
            except ValueError:
                valid = False
            title, abstract, published = value('title'), value('summary'), value('published')
            authors = tuple(' '.join((a.findtext(_ATOM + 'name') or '').split())
                            for a in entry.findall(_ATOM + 'author'))
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', published):
                    raise ValueError
                day = date.fromisoformat(published[:10])
            except ValueError:
                raise InvalidResponse('arXiv entry has missing/invalid publication date') from None
            if (not valid or not title or len(title) > 10000 or not abstract or len(abstract) > 200000
                    or not authors or any(not a or len(a) > 1000 for a in authors) or len(authors) > 3000):
                raise InvalidResponse('arXiv entry has missing/invalid metadata')
            stable_id = 'arxiv:' + re.sub(r'v\d+$', '', identifier)
            if stable_id in seen:
                continue
            seen.add(stable_id)
            papers.append(Paper(paper_id=stable_id, title=title, abstract=abstract, year=day.year,
                url='https://arxiv.org/abs/' + identifier, citation_count=None,
                publication_date=day.isoformat(), authors=authors, source_provider='arxiv'))
        return papers[:limit]
