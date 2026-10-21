"""Offline native retrieval regressions; synthetic transports, no research calls."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from sage.arxiv import ArxivSource, _paced_request
from sage.autonomous.mcp import TOOLS
from sage.autonomous.service import ResearchService
from sage.errors import RateLimited, TransientProviderError
from sage.providers import HTTPResponse
from sage.types import Paper


EMPTY_ATOM = b'<feed xmlns="http://www.w3.org/2005/Atom"/>'


def crossref(items):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps({'message': {'items': items}}).encode()
    return response


class NativeRetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = ResearchService(self.root / 'private', self.root, 'synthetic topic')
        blocker = patch('sage.autonomous.service.OpenAIModel.from_env',
                        side_effect=AssertionError('No paid model calls in these tests'))
        blocker.start()
        self.addCleanup(blocker.stop)

    def search(self, query='reasoning robustness'):
        return self.service.call('search', {'query': query})

    def test_keyword_provenance_and_suggestions_do_not_make_hidden_requests(self):
        transport = Mock(return_value=HTTPResponse(200, EMPTY_ATOM))
        query = 'reasoning robustness domain shift task transfer'
        with patch('sage.arxiv._metadata_https_request', transport), \
             patch('sage.arxiv._LAST_FINISHED', 0.0), \
             patch('sage.autonomous.service.urlopen', return_value=crossref([])):
            receipt = self.search(query)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(self.service.tool_calls, 1)
        self.assertEqual(receipt['query'], query)
        self.assertEqual(receipt['arxiv_query']['terms'], query.split())
        self.assertEqual(receipt['arxiv_query']['search_query'],
                         ' AND '.join(f'all:"{term}"' for term in query.split()))
        self.assertEqual(receipt['arxiv_query']['suggested_queries'],
                         ['reasoning robustness domain shift', 'reasoning robustness'])
        self.assertEqual(receipt['retrieval_status'], 'empty')
        self.assertEqual(receipt['comparison_status'], 'relevance_not_assessed')
        self.assertIn(ArxivSource.query_instructions, next(x[1] for x in TOOLS if x[0] == 'search'))

    def test_unknown_retry_after_pauses_shared_native_arxiv_but_keeps_fallback(self):
        transport = Mock(return_value=HTTPResponse(429, b'', None))
        metadata = [{'DOI': '10.fixture/only', 'title': ['Synthetic title'], 'type': 'peer-review'}]
        with patch('sage.arxiv._metadata_https_request', transport), \
             patch('sage.arxiv._LAST_FINISHED', 0.0), \
             patch('sage.arxiv.time.sleep'), \
             patch('sage.autonomous.service.urlopen', return_value=crossref(metadata)) as fallback:
            first = self.search()
            second = self.search('another topic')
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(fallback.call_count, 2)
        self.assertEqual(self.service.tool_calls, 2)
        self.assertTrue(first['failures'][0]['network_request'])
        self.assertFalse(second['failures'][0]['network_request'])
        self.assertEqual(second['failures'][0]['error_code'], 'rate_limited')
        self.assertIsNone(second['failures'][0]['retry_after_seconds'])
        self.assertEqual(second['failures'][0]['http_status'], 429)
        self.assertTrue(self.service.search_cooldown['paused'])
        self.assertEqual(second['results'][0]['evidence_scope'], 'metadata_only')
        self.assertIsNone(second['results'][0]['citation_count'])
        self.assertEqual(second['provider_metadata']['doi:10.fixture/only']['work_type'], 'peer-review')
        self.assertIn('NoEvidence', second['reading_limits']['doi:10.fixture/only']['limitation'])

    def test_known_retry_after_resumes_only_after_deadline_and_existing_pacing(self):
        clock = [100.0]
        waits = []
        state = {}
        transport = Mock(side_effect=[HTTPResponse(429, b'', 20), HTTPResponse(200, EMPTY_ATOM)])
        first = ArxivSource(transport=transport, cooldown=state)
        second = ArxivSource(transport=transport, cooldown=state)

        def sleep(seconds):
            waits.append(seconds)
            clock[0] += seconds

        with patch('sage.arxiv.time.monotonic', side_effect=lambda: clock[0]), \
             patch('sage.arxiv.time.sleep', side_effect=sleep), \
             patch('sage.arxiv._LAST_FINISHED', 0.0):
            self.assertEqual(_paced_request(first._request_with_cooldown, 'fixture', {}, 35, 100).status, 429)
            with self.assertRaises(RateLimited) as error:
                _paced_request(second._request_with_cooldown, 'fixture', {}, 35, 100)
            self.assertEqual(error.exception.retry_after_seconds, 17)
            self.assertFalse(error.exception.network_request)
            self.assertEqual(transport.call_count, 1)
            clock[0] = 120.0
            self.assertEqual(_paced_request(second._request_with_cooldown, 'fixture', {}, 35, 100).status, 200)
        self.assertEqual(transport.call_count, 2)
        self.assertIn(3.0, waits)

    def test_two_native_slots_share_cooldown_before_queued_transport_dispatch(self):
        service = ResearchService(self.root / 'team-private', self.root, 'synthetic topic', researchers=2)
        for slot in range(2):
            worktree = self.root / f'worker-{slot}'
            worktree.mkdir()
            service.team.register(slot, f'worker-{slot}', worktree, f'session-{slot}')
        entered = threading.Event()
        release = threading.Event()

        def transport(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return HTTPResponse(429, b'', 60)

        with patch('sage.arxiv._metadata_https_request', side_effect=transport) as network, \
             patch('sage.arxiv._LAST_FINISHED', 0.0), patch('sage.arxiv.time.sleep'), \
             patch('sage.autonomous.service.urlopen', return_value=crossref([])), \
             ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.call, 'search', {'query': 'reasoning models'}, slot=0)
            if not entered.wait(3):
                self.fail('The synthetic transport was not reached: ' + repr(first.result(timeout=1)['failures']))
            second = pool.submit(service.call, 'search', {'query': 'robustness transfer'}, slot=1)
            release.set()
            results = [first.result(timeout=5), second.result(timeout=5)]
        self.assertEqual(network.call_count, 1)
        self.assertEqual(service.tool_calls, 2)
        self.assertEqual(sorted(r['failures'][0]['network_request'] for r in results), [False, True])
        self.assertTrue(all(r['failures'][0]['retry_after_seconds'] > 0 for r in results))

    def test_readability_is_separate_from_paper_constructor_and_preserves_source(self):
        papers = [Paper('doi:10.fixture/metadata', 'Metadata', evidence_scope='metadata_only'),
                  Paper('doi:10.fixture/abstract', 'Abstract', abstract='Original fixture abstract.'),
                  Paper('arxiv:2401.12345', 'Official text candidate', url='https://arxiv.org/abs/2401.12345')]
        with patch('sage.autonomous.service.ArxivSource.search', return_value=papers), \
             patch('sage.autonomous.service.urlopen', side_effect=AssertionError('No fallback expected')):
            result = self.search()
        for item in result['results']:
            self.assertEqual(Paper(**item).paper_id, item['paper_id'])
        limits = result['reading_limits']
        self.assertFalse(limits[papers[0].paper_id]['readable_text_available'])
        self.assertFalse(limits[papers[0].paper_id]['official_arxiv_text_lookup_supported'])
        self.assertTrue(limits[papers[1].paper_id]['readable_text_available'])
        self.assertTrue(limits[papers[2].paper_id]['official_arxiv_text_lookup_supported'])
        self.assertEqual(self.service.papers[papers[1].paper_id]['abstract'], 'Original fixture abstract.')

    def test_failure_details_keep_safe_code_and_status_without_exception_text(self):
        error = TransientProviderError('SECRET_AUTH_DO_NOT_EXPORT')
        error.http_status = 503
        with patch('sage.autonomous.service.ArxivSource.search', side_effect=error), \
             patch('sage.autonomous.service.urlopen', return_value=crossref([])):
            receipt = self.search()
        self.assertNotIn('SECRET_AUTH_DO_NOT_EXPORT', json.dumps(receipt))
        self.assertEqual(receipt['failures'][0]['error_code'], 'transient_provider_error')
        self.assertEqual(receipt['failures'][0]['http_status'], 503)
        self.assertEqual(receipt['retrieval_status'], 'degraded')

    def test_arxiv_http_status_is_preserved_by_real_adapter_without_network(self):
        source = ArxivSource(transport=Mock(return_value=HTTPResponse(503, b'')))
        with patch('sage.arxiv._LAST_FINISHED', 0.0), self.assertRaises(TransientProviderError) as error:
            asyncio.run(source.search('reasoning models', limit=2))
        self.assertEqual(error.exception.http_status, 503)

    def test_queued_worker_checks_shutdown_before_transport(self):
        transport = Mock()
        guard = Mock(side_effect=ValueError('Run has stopped'))
        source = ArxivSource(transport=transport, cooldown={}, before_request=guard)
        with patch('sage.arxiv._LAST_FINISHED', 0.0), self.assertRaisesRegex(ValueError, 'stopped'):
            _paced_request(source._request_with_cooldown, 'fixture', {}, 35, 100)
        guard.assert_called_once()
        transport.assert_not_called()

    def test_event_envelope_cannot_be_overwritten_by_source_fields(self):
        self.service.trace_context.request_id = 'trusted-request'
        self.service.event('search', time='old-query-start', event_sequence=999,
                           request_id='untrusted-request', query_started_at='recorded-start')
        event = json.loads((self.service.private / 'events.jsonl').read_text().splitlines()[-1])
        self.assertNotEqual(event['time'], 'old-query-start')
        self.assertEqual(event['request_id'], 'trusted-request')
        self.assertEqual(event['event_sequence'], 1)
        self.assertEqual(event['query_started_at'], 'recorded-start')


if __name__ == '__main__':
    unittest.main()
