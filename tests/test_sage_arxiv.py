"""Synthetic Atom/transport tests: never evidence of live arXiv availability."""
import asyncio
from dataclasses import replace
import json
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from sage.arxiv import ArxivSource, _paced_request, _query
from sage.config import RunConfig
from sage.errors import ConfigurationError, InvalidResponse, ProviderError, TransientProviderError
from sage.providers import (HTTPResponse, SemanticScholarSource, _https_request,
                            _metadata_https_request, paper_source_from_env)
from sage.types import Paper, paper_record
from sage.fixtures import FixtureModel, FixtureSource
from sage.orchestration import run


def atom(identifier='2401.12345v2', title='Retrieval evaluation', published='2024-01-02T00:00:00Z'):
    return (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/{identifier}</id>'
            f'<title>{title}</title><summary>Real metadata shape; synthetic test content.</summary>'
            f'<published>{published}</published><author><name>A. Scientist</name></author>'
            '<author><name>B. Researcher</name></author></entry></feed>').encode()


class ArxivTests(unittest.TestCase):
    def test_metadata_identity_version_authors_dates_scope(self):
        paper = ArxivSource.parse(atom(), limit=5)[0]
        self.assertEqual(paper.paper_id, 'arxiv:2401.12345')
        self.assertEqual(paper.url, 'https://arxiv.org/abs/2401.12345v2')
        self.assertEqual(paper.authors, ('A. Scientist', 'B. Researcher'))
        self.assertEqual(paper.publication_date, '2024-01-02')
        self.assertEqual(paper.evidence_scope, 'abstract_only')
        self.assertIsNone(paper.citation_count)
        self.assertEqual(paper_record(paper)['source_provider'], 'arxiv')
        self.assertEqual(ArxivSource.parse(atom(identifier='cs/9901001'), limit=1)[0].paper_id, 'arxiv:cs/9901001')

    def test_invalid_xml_and_metadata_fail_closed(self):
        for body in (b'<!DOCTYPE feed [<!ENTITY x "boom">]><feed/>', b'<html/>', b'bad',
                     atom(identifier='../../evil'), atom(published='2024-02-31T00:00:00Z'),
                     atom(title=''), atom().replace(b'<name>A. Scientist</name>', b'<name/>'),
                     atom().replace(b'arxiv.org/abs/', b'evil.test/abs/')):
            with self.subTest(body=body), self.assertRaises(InvalidResponse):
                ArxivSource.parse(body, limit=5)

    def test_versions_deduplicate_and_empty_feed_valid(self):
        first = atom().decode().split('<entry>')[1].split('</entry>')[0]
        body = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'+first+'</entry><entry>'+
                first.replace('v2', 'v3')+'</entry></feed>').encode()
        self.assertEqual(len(ArxivSource.parse(body, limit=5)), 1)
        self.assertEqual(ArxivSource.parse(b'<feed xmlns="http://www.w3.org/2005/Atom"/>', limit=5), [])

    def test_source_selection_default_explicit_and_invalid(self):
        self.assertIsInstance(paper_source_from_env(env={}), SemanticScholarSource)
        env={'SAGE_PAPER_PROVIDER':'arxiv','SAGE_USE_ENV_PROXY':'true','HTTPS_PROXY':'http://proxy.test:80',
             'SAGE_OPENAI_API_KEY':'secret','SAGE_SEMANTIC_SCHOLAR_API_KEY':'other-secret'}
        source=paper_source_from_env(env=env)
        self.assertIsInstance(source,ArxivSource)
        self.assertEqual(source._transport.keywords['proxy_url'],'http://proxy.test:80')
        with self.assertRaises(ConfigurationError): paper_source_from_env(env={'SAGE_PAPER_PROVIDER':'invalid'})
        with self.assertRaises(ConfigurationError): ArxivSource.from_env(env={'SAGE_USE_ENV_PROXY':'true'})

    def test_graph_method_never_fabricates_edges_or_calls_network(self):
        transport=Mock()
        source=ArxivSource(transport=transport)
        with self.assertRaises(ConfigurationError):
            asyncio.run(source.related(Paper('id','title'),direction='citations',limit=5))
        transport.assert_not_called()

    def test_transport_endpoint_and_credentials_guard(self):
        for url in ('http://export.arxiv.org/api/query','https://export.arxiv.org/pdf/1',
                    'https://evil.test/api/query','https://export.arxiv.org:443/api/query'):
            with self.assertRaises(ConfigurationError): _metadata_https_request(url,{},10,100)
        with self.assertRaises(ConfigurationError):
            _https_request('https://export.arxiv.org/api/query',{},10,100)
        with self.assertRaises(ConfigurationError):
            _metadata_https_request('https://export.arxiv.org/api/query',{'Authorization':'secret'},10,100)

    def test_transport_connect_redirect_tls_and_no_fallback(self):
        connection=Mock()
        connection.getresponse.return_value=Mock(status=302)
        with patch('sage.providers.http.client.HTTPSConnection',return_value=connection) as factory:
            reply=_metadata_https_request('https://export.arxiv.org/api/query?x=1',{},10,100,
                                          proxy_url='http://proxy.test:80')
        self.assertEqual(reply.status,302)
        connection.set_tunnel.assert_called_once_with('export.arxiv.org',443)
        connection.getresponse.return_value.read1.assert_not_called()
        connection.connect.side_effect=OSError('failed')
        with patch('sage.providers.http.client.HTTPSConnection',return_value=connection) as factory:
            with self.assertRaises(OSError):
                _metadata_https_request('https://export.arxiv.org/api/query',{},10,100,
                                        proxy_url='http://proxy.test:80')
            self.assertEqual(factory.call_count,1)

    def test_pacing_waits_three_seconds_after_failure(self):
        clock=[100.0];waits=[]
        def sleep(seconds): waits.append(seconds);clock[0]+=seconds
        with patch('sage.arxiv.time.monotonic',side_effect=lambda:clock[0]), \
             patch('sage.arxiv.time.sleep',side_effect=sleep),patch('sage.arxiv._LAST_FINISHED',0.0):
            failing=Mock(side_effect=OSError('failed'))
            with self.assertRaises(OSError):_paced_request(failing,'url',{},10,100)
            transport=Mock(return_value=HTTPResponse(200,b''))
            _paced_request(transport,'url',{},10,100)
            self.assertEqual(waits,[0.0,3.0])
            self.assertAlmostEqual(transport.call_args.args[2],7.0)
            with self.assertRaises(TimeoutError):_paced_request(transport,'url',{},2,100)
            self.assertEqual(transport.call_count,1)

    def test_search_parameters_date_filter_and_no_keys(self):
        transport=Mock(return_value=HTTPResponse(200,atom()))
        source=ArxivSource(transport=transport)
        with patch('sage.arxiv._paced_request',side_effect=lambda t,*args:t(*args)):
            papers=asyncio.run(source.search('retrieval evaluation',limit=2,publication_date='2024'))
            self.assertEqual(len(papers),1)
            self.assertEqual(asyncio.run(source.search('retrieval',limit=2,publication_date='2025')),[])
        url,headers,_,_=transport.call_args.args
        self.assertEqual(set(headers),{'Accept','User-Agent'})
        params=parse_qs(urlsplit(url).query)
        self.assertIn('submittedDate:[202501010000 TO 202512312359]',params['search_query'][0])
        self.assertEqual(params['max_results'],['2'])
        self.assertEqual(source.request_count,2)
        self.assertIn(' AND ',_query('citation verification'))
        self.assertIn(' OR ',_query('citation verification',thematic=True))

    def test_http_errors_size_and_bad_atom_propagate(self):
        for reply,exc in ((HTTPResponse(429,b''),TransientProviderError),(HTTPResponse(403,b''),ProviderError),
                          (HTTPResponse(200,b'x'*101),InvalidResponse),(HTTPResponse(200,b'<html/>'),InvalidResponse)):
            source=ArxivSource(transport=Mock(return_value=reply),max_response_bytes=100)
            with patch('sage.arxiv._paced_request',side_effect=lambda t,*args:t(*args)),self.assertRaises(exc):
                asyncio.run(source.search('retrieval',limit=1))

    def test_topic_time_chain_handoff_never_uses_graph(self):
        # Full controller regression with synthetic source data, not a live result.
        class Source(FixtureSource):
            chain_relation='topic_time'
            prompt_policy=ArxivSource.prompt_policy
            async def related(self,*args,**kwargs): raise AssertionError('Graph should not be called')
            async def topic_related(self,paper,*,limit,publication_date=None):
                return await super().related(paper,direction='citations',limit=limit)
        result=asyncio.run(run('synthetic',FixtureModel(),Source(),
                          config=RunConfig(discussion_mode='hybrid',max_chain_length=2)))
        self.assertTrue(result.status.startswith('completed'),result.errors)
        self.assertEqual(len(result.candidates),2)
        for candidate in result.candidates:
            self.assertEqual(candidate.chain.relation,'topic_time')
            self.assertIn('no citation',candidate.chain.text)
        self.assertTrue(any(e.get('relation')=='topic_time' for e in result.audit))
        self.assertEqual(result.experiment.status,'proposal_only')
