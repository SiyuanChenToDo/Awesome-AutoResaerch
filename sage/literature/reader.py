"""Read authorized official arXiv text; never follow paper-provided download URLs."""
from __future__ import annotations
import asyncio
from functools import partial
from html.parser import HTMLParser
from io import BytesIO
import re
from urllib.parse import urlsplit
from ..checkpoints import digest
from ..errors import InvalidResponse, TransientProviderError, BudgetExceeded
from ..providers import _metadata_https_request, _environment_proxy, HTTPResponse

ID = r'(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z.\-]+/\d{7})(?:v[1-9]\d*)?'


def arxiv_identity(paper):
    parts = urlsplit(paper.url)
    if parts.scheme == 'https' and parts.netloc == 'arxiv.org' and parts.path.startswith('/abs/'):
        identity = parts.path[5:]
    else:
        identity = paper.paper_id.removeprefix('arxiv:') if paper.paper_id.startswith('arxiv:') else ''
    return identity if re.fullmatch(ID, identity) else None


class ArticleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.heading = 'Preamble'
        self.current = []
        self.sections = []
        self.in_heading = False
        self.heading_parts = []
        self.active = False

    def flush(self):
        text = re.sub(r'\s+', ' ', ' '.join(self.current)).strip()
        if text:
            self.sections.append({'heading': self.heading, 'text': text})
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag == 'article' and 'ltx_document' in dict(attrs).get('class', '').split():
            self.active = True
        if not self.active:
            return
        if tag in ('script', 'style', 'nav'):
            self.skip += 1
        if self.skip:
            return
        if re.fullmatch('h[1-6]', tag):
            self.flush(); self.in_heading = True; self.heading_parts = []
        elif tag == 'math':
            alternative = dict(attrs).get('alttext')
            if alternative:
                self.current.append(' [formula: ' + alternative + '] ')
        elif tag in ('p', 'div', 'li', 'tr', 'td', 'br'):
            self.current.append(' ')

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag == 'article':
            self.flush(); self.active = False; return
        if tag in ('script', 'style', 'nav') and self.skip:
            self.skip -= 1
        elif not self.skip and re.fullmatch('h[1-6]', tag):
            self.heading = ' '.join(self.heading_parts).strip() or 'Untitled'
            self.in_heading = False

    def handle_data(self, data):
        if self.active and not self.skip:
            (self.heading_parts if self.in_heading else self.current).append(data)


def html_article(body, url):
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        raise InvalidResponse('arXiv HTML is not UTF-8') from None
    if 'ltx_document' not in text:
        return None  # Do not mistake a generic error/landing page for a paper.
    parser = ArticleHTML(); parser.feed(text); parser.flush()
    sections = parser.sections
    if sum(len(s['text']) for s in sections) < 500:
        return None
    sections, truncated = bound_sections(sections)
    return {'sections': sections, 'references': [], 'source_url': url,
            'format': 'arxiv_html', 'source_sha256': digest(sections),
            'text_truncated': truncated, 'reading_scope': 'retrieved_article_text_not_independently_verified'}


def bound_sections(sections, limit=400000):
    total = sum(len(s['text']) for s in sections)
    if total <= limit:
        return sections, False
    # Bound checkpoint size and show the limitation instead of claiming completeness.
    result = []
    for section in sections:
        if limit <= 0:
            break
        result.append({**section, 'text': section['text'][:limit]})
        limit -= len(result[-1]['text'])
    return result, True


def pdf_article(body, url):
    if not body.startswith(b'%PDF-'):
        return None
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        sections = [{'heading': f'PDF page {i+1}', 'text': page.extract_text() or ''}
                    for i, page in enumerate(reader.pages[:60])]
    except Exception:
        raise InvalidResponse('arXiv PDF text extraction failed') from None
    if sum(len(s['text']) for s in sections) < 500:
        return None
    sections, truncated = bound_sections(sections)
    return {'sections': sections, 'references': [], 'source_url': url,
            'format': 'arxiv_pdf_text', 'source_sha256': digest(sections),
            'reading_scope': 'text_extraction_only_tables_math_may_be_incomplete',
            'text_truncated': truncated or len(reader.pages) > 60,
            'page_limit': 60, 'available_pages': len(reader.pages)}


async def read_article(runtime, paper, *, transport=None):
    identity = arxiv_identity(paper)
    if not identity:
        return None
    transport = transport or partial(_metadata_https_request, proxy_url=_environment_proxy(__import__('os').environ))
    for kind, parser in (('html', html_article), ('pdf', pdf_article)):
        url = 'https://arxiv.org/' + kind + '/' + identity
        async def operation():
            try:
                reply = await asyncio.to_thread(transport, url,
                    {'Accept': 'text/html' if kind == 'html' else 'application/pdf', 'User-Agent': 'SAGE-evidence-reader/1'},
                    runtime.config.request_timeout_seconds, 10_000_000)
            except Exception:
                raise TransientProviderError('Official paper text request failed') from None
            if not isinstance(reply, HTTPResponse) or not isinstance(reply.body, bytes) or len(reply.body) > 10_000_000:
                raise InvalidResponse('Invalid paper text response')
            if reply.status != 200:
                return {'available': False, 'status': reply.status}
            article = await asyncio.to_thread(parser, reply.body, url)
            return {'available': article is not None, 'article': article}
        try:
            value = await runtime.call('search', 'literature.read_' + kind, operation,
                                       cache_input={'url': url, 'parser_version': 1})
        except BudgetExceeded:
            raise
        except (InvalidResponse, TransientProviderError):
            runtime.event('literature.read', 'unavailable', paper_id=paper.paper_id, format=kind)
            continue
        if value['available']:
            runtime.event('literature.read', 'retrieved', paper_id=paper.paper_id, format=kind,
                          source_sha256=value['article']['source_sha256'])
            return value['article']
        runtime.event('literature.read', 'unavailable', paper_id=paper.paper_id, format=kind,
                      http_status=value.get('status'))
    return None
