"""Opt-in official environment proxy regression tests; no network requests."""
import http.client
import ssl
import types
import unittest
from unittest.mock import Mock, patch

from sage.errors import ConfigurationError, InvalidResponse, TransientProviderError
from sage.providers import (OpenAIConfig, OpenAIModel, SemanticScholarSource,
                            _environment_proxy, _https_request, _provider_error)

URL = 'https://api.semanticscholar.org/graph/v1/paper/search?query=test'
PROXY = 'http://official-proxy.test:8080'
ENV = {'SAGE_USE_ENV_PROXY': 'true', 'HTTPS_PROXY': PROXY}


class ProxyTests(unittest.TestCase):
    def test_default_ignores_ambient_proxy(self):
        self.assertIsNone(_environment_proxy({'HTTPS_PROXY': PROXY}))
        self.assertIsNone(_environment_proxy(dict(ENV, SAGE_USE_ENV_PROXY='false')))

    def test_opt_in_and_lowercase(self):
        self.assertEqual(_environment_proxy(ENV), PROXY)
        self.assertEqual(_environment_proxy({'SAGE_USE_ENV_PROXY': 'true', 'https_proxy': PROXY}), PROXY)

    def test_no_proxy_cannot_bypass_explicit_proxy(self):
        self.assertEqual(_environment_proxy(dict(ENV, NO_PROXY='*', no_proxy='*')), PROXY)

    def test_missing_conflicting_and_invalid_opt_in_fail_closed(self):
        for env in ({'SAGE_USE_ENV_PROXY': 'true'}, dict(ENV, https_proxy='http://other.test'),
                    dict(ENV, SAGE_USE_ENV_PROXY='maybe')):
            with self.subTest(env=env), self.assertRaises(ConfigurationError):
                _environment_proxy(env)

    def test_unsafe_proxy_urls_rejected_without_echo(self):
        for value in ('https://proxy.test', 'socks5://proxy.test', 'http://user:secret@proxy.test',
                      'http://proxy.test/path', 'http://proxy.test?secret', 'http://proxy.test#secret',
                      'http://proxy.test:99999', 'http://proxy.test:0', 'http://proxy.test\n', 1):
            with self.subTest(value=value), self.assertRaises(ConfigurationError) as caught:
                OpenAIConfig(model='test', api_key='test-secret', proxy_url=value)
            self.assertNotIn('test-secret', str(caught.exception))
            self.assertNotIn('proxy.test', str(caught.exception))

    def test_model_proxy_snapshot_hidden_from_repr(self):
        env = dict(ENV, SAGE_MAIN_MODEL='test', SAGE_OPENAI_API_KEY='test-secret')
        config = OpenAIConfig.from_env(env=env)
        env['HTTPS_PROXY'] = 'http://other.test'
        self.assertEqual(config.proxy_url, PROXY)
        self.assertNotIn(PROXY, repr(config))
        self.assertNotIn('test-secret', repr(config))

    def test_model_and_embedding_transport_preserve_security(self):
        for name in ('DefaultAsyncHttpxClient', 'DefaultAsyncHttpx2Client'):
            factory = Mock()
            sdk = types.SimpleNamespace(AsyncOpenAI=Mock(), AsyncAzureOpenAI=Mock(), **{name: factory})
            model = OpenAIModel(OpenAIConfig(model='test', api_key='test-secret', proxy_url=PROXY,
                embedding_model='embed', embedding_endpoint='https://embed.test',
                embedding_api_key='embed-secret', embedding_api_version='v1'))
            with patch('sage.providers.importlib.import_module', return_value=sdk):
                model._make_client()
                model._make_client(embeddings=True)
            for call in factory.call_args_list:
                self.assertEqual(call.kwargs, dict(timeout=30.0, follow_redirects=False,
                                                  trust_env=False, proxy=PROXY))
            self.assertEqual(sdk.AsyncOpenAI.call_args.kwargs['max_retries'], 0)
            self.assertEqual(sdk.AsyncAzureOpenAI.call_args.kwargs['max_retries'], 0)

    def test_paper_from_env_snapshots_proxy(self):
        source = SemanticScholarSource.from_env(env=ENV)
        self.assertEqual(source._transport.keywords, {'proxy_url': PROXY})

    def test_connect_has_no_api_headers_and_redirect_not_followed(self):
        connection = Mock()
        connection.getresponse.return_value = Mock(status=302)
        with patch('sage.providers.http.client.HTTPSConnection', return_value=connection) as factory:
            response = _https_request(URL, {'x-api-key': 'test-secret'}, 10, 100, proxy_url=PROXY)
        factory.assert_called_once_with('official-proxy.test', 8080, timeout=10)
        connection.set_tunnel.assert_called_once_with('api.semanticscholar.org', 443)
        self.assertEqual(response.status, 302)
        connection.request.assert_called_once_with('GET', '/graph/v1/paper/search?query=test',
                                                   headers={'x-api-key': 'test-secret'})
        connection.getresponse.return_value.read1.assert_not_called()
        connection.close.assert_called_once()

    def test_connect_failure_no_origin_request_or_direct_fallback(self):
        connection = Mock()
        connection.connect.side_effect = OSError('Tunnel connection failed: 403 Forbidden')
        with patch('sage.providers.http.client.HTTPSConnection', return_value=connection) as factory:
            with self.assertRaises(OSError) as caught:
                _https_request(URL, {'x-api-key': 'test-secret'}, 10, 100, proxy_url=PROXY)
        self.assertEqual(factory.call_count, 1)
        connection.request.assert_not_called()
        connection.close.assert_called_once()
        self.assertIsInstance(_provider_error(caught.exception, 'Paper provider'), TransientProviderError)

    def test_tunnel_tls_verifies_origin_not_proxy(self):
        # Exercise real stdlib HTTPSConnection CONNECT/TLS setup with fake socket IO.
        connection = http.client.HTTPSConnection('official-proxy.test', 8080, timeout=10)
        connection.set_tunnel('api.semanticscholar.org', 443)
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(connection._context.check_hostname)
        context = Mock()
        connection._context = context
        with patch.object(connection, '_create_connection', return_value=Mock()), \
             patch.object(connection, '_tunnel') as tunnel:
            connection.connect()
        tunnel.assert_called_once()
        self.assertEqual(context.wrap_socket.call_args.kwargs['server_hostname'], 'api.semanticscholar.org')
        connection.close()

    def test_proxy_retains_size_deadline_and_host_guards(self):
        with self.assertRaises(ConfigurationError):
            _https_request('https://evil.test/graph/v1/search', {}, 10, 100, proxy_url=PROXY)
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200)
        connection.getresponse.return_value.getheader.return_value = '101'
        with patch('sage.providers.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaises(InvalidResponse):
                _https_request(URL, {}, 10, 100, proxy_url=PROXY)
        connection.close.assert_called_once()
        connection.reset_mock()
        with patch('sage.providers.http.client.HTTPSConnection', return_value=connection), \
             patch('sage.providers.time.monotonic', side_effect=[0, 11]):
            with self.assertRaises(TimeoutError):
                _https_request(URL, {}, 10, 100, proxy_url=PROXY)
        connection.request.assert_not_called()
        connection.close.assert_called_once()
