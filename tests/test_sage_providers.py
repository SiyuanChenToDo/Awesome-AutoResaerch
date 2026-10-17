"""Provider contract tests with fake SDKs and HTTP transports; no network or keys."""
import asyncio
import json
import math
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sage.errors import ConfigurationError, InvalidResponse, ProviderError, TransientProviderError
from sage.providers import HTTPResponse, OpenAIConfig, OpenAIModel, SemanticScholarSource, _https_request, parse_bool
from sage.types import Paper

SECRET = "never-print-this-test-credential"


def sdk_reply(text="bounded response", reason="stop"):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=text, refusal=None), finish_reason=reason)])


def fake_sdk_client(reply=None, error=None):
    create = AsyncMock(return_value=reply if reply is not None else sdk_reply(), side_effect=error)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)),
                                 embeddings=types.SimpleNamespace(create=AsyncMock()), close=AsyncMock())


def record(paper_id="paper-1", **values):
    result = {"paperId": paper_id, "title": "A real metadata record", "abstract": "Abstract only", "year": 2024,
              "citationCount": 3, "url": "https://www.semanticscholar.org/paper/" + paper_id}
    result.update(values)
    return result


def http_reply(data=None, status=200, **values):
    return HTTPResponse(status, json.dumps(dict(data=[] if data is None else data, **values)).encode())


class FakeTransport:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, headers, timeout, max_bytes):
        self.calls.append((url, headers, timeout, max_bytes))
        if not self.replies:
            raise AssertionError("Unexpected additional HTTP request")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class StatusError(Exception):
    def __init__(self, status):
        self.status_code = status
        super().__init__(SECRET)


class ConfigTests(unittest.TestCase):
    def test_strict_bool(self):
        for value in ("False", "false", "0", "off", " NO ", False):
            with self.subTest(value=value):
                self.assertIs(parse_bool(value), False)
        for value in ("true", "1", "on", " YES ", True):
            self.assertIs(parse_bool(value), True)
        for value in ("", "perhaps", None, 2, 0, [], SECRET):
            with self.subTest(value=value), self.assertRaises(ConfigurationError) as caught:
                parse_bool(value)
            self.assertNotIn(SECRET, str(caught.exception))

    def test_import_is_dependency_and_network_free(self):
        code = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'openai':
        raise AssertionError('SDK imported eagerly')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import sage.providers
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_original_env_names_and_false_select_openai(self):
        config = OpenAIConfig.from_env(env={"MAIN_LLM_MODEL": "main-deployment", "OPENAI_API_KEY": SECRET,
                                          "is_azure": "False"})
        self.assertFalse(config.is_azure)
        self.assertEqual(config.model, "main-deployment")
        self.assertNotIn(SECRET, repr(config))

    def test_aliases_and_cheap_role(self):
        config = OpenAIConfig.from_env(role="cheap", env={"SAGE_CHEAP_MODEL": "cheap-model",
            "CHEAP_LLM_MODEL": "ignored", "SAGE_OPENAI_API_KEY": SECRET})
        self.assertEqual(config.model, "cheap-model")

    def test_azure_requires_all_configuration(self):
        complete = {"is_azure": "true", "MAIN_LLM_MODEL": "azure-deployment", "AZURE_OPENAI_KEY": SECRET,
                    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com", "AZURE_OPENAI_API_VERSION": "version"}
        config = OpenAIConfig.from_env(env=complete)
        self.assertTrue(config.is_azure)
        for key in ("MAIN_LLM_MODEL", "AZURE_OPENAI_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION"):
            values = dict(complete)
            values.pop(key)
            with self.subTest(key=key), self.assertRaises(ConfigurationError) as caught:
                OpenAIConfig.from_env(env=values)
            self.assertNotIn(SECRET, str(caught.exception))

    def test_missing_openai_configuration_no_client_or_network(self):
        for env in ({}, {"MAIN_LLM_MODEL": "model"}, {"OPENAI_API_KEY": SECRET},
                    {"SAGE_MAIN_MODEL": "  ", "OPENAI_API_KEY": SECRET}):
            with self.subTest(env=list(env)), self.assertRaises(ConfigurationError) as caught:
                OpenAIModel.from_env(env=env)
            self.assertNotIn(SECRET, str(caught.exception))

    def test_unexpected_config_and_insecure_endpoint_rejected(self):
        base = {"MAIN_LLM_MODEL": "main", "OPENAI_API_KEY": SECRET}
        for endpoint in ("http://unsafe.test", "https://user:password@example.com", "https://example.com?q=" + SECRET,
                         "https://example.com/#fragment", "https://example.com\n/path"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ConfigurationError) as caught:
                OpenAIConfig.from_env(env=dict(base, OPENAI_BASE_URL=endpoint))
            self.assertNotIn(SECRET, str(caught.exception))
        with self.assertRaises(ConfigurationError):
            OpenAIConfig.from_env(env=base, role="other")
        with self.assertRaises(ConfigurationError):
            OpenAIConfig.from_env(env=dict(base, is_azure="ambiguous"))

    def test_timeout_and_response_caps_are_finite_positive(self):
        for value in (0, -1, math.inf, math.nan, 301, True, "30"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                SemanticScholarSource(timeout=value)
        for value in (0, -1, 10_000_001, True):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                SemanticScholarSource(max_response_bytes=value)

    def test_direct_configuration_cannot_skip_validation(self):
        for values in ({"model": "main"}, {"model": "", "api_key": SECRET},
                       {"model": "main", "api_key": SECRET, "is_azure": "False"},
                       {"model": "main", "api_key": SECRET, "endpoint": "http://unsafe.test"},
                       {"model": "main", "api_key": SECRET, "is_azure": True}):
            with self.subTest(keys=list(values)), self.assertRaises(ConfigurationError) as caught:
                OpenAIConfig(**values)
            self.assertNotIn(SECRET, str(caught.exception))

    def test_optional_and_separate_embedding_configuration(self):
        base = {"SAGE_MAIN_MODEL": "main", "OPENAI_API_KEY": SECRET}
        self.assertFalse(OpenAIModel.from_env(env=base).embedding_enabled)
        self.assertTrue(OpenAIModel.from_env(env=dict(base, EMBEDDING_MODEL="embedding")).embedding_enabled)
        with self.assertRaises(ConfigurationError):
            OpenAIModel.from_env(env=dict(base, EMBEDDING_API_ENDPOINT="https://embedding.azure.test"))
        config = OpenAIConfig.from_env(env=dict(base, EMBEDDING_MODEL="embedding",
            EMBEDDING_API_ENDPOINT="https://embedding.azure.test", EMBEDDING_API_KEY=SECRET,
            AZURE_OPENAI_API_VERSION="version"))
        self.assertEqual(config.embedding_api_version, "version")
        self.assertNotIn(SECRET, repr(config))


class ModelTests(unittest.IsolatedAsyncioTestCase):
    def model(self, client=None, **kwargs):
        return OpenAIModel.from_env(env={"SAGE_MAIN_MODEL": "model", "OPENAI_API_KEY": SECRET,
                                        "EMBEDDING_MODEL": "embed-model"}, client=client, **kwargs)

    async def test_sdk_construction_lazy_timeout_and_no_retries(self):
        client = fake_sdk_client()
        sdk = types.SimpleNamespace(AsyncOpenAI=Mock(return_value=client), DefaultAsyncHttpxClient=Mock())
        with patch("sage.providers.importlib.import_module", return_value=sdk) as importer:
            model = self.model()
            importer.assert_not_called()
            self.assertEqual(await model.complete("ideas", "prompt", max_tokens=123), "bounded response")
        kwargs = sdk.AsyncOpenAI.call_args.kwargs
        self.assertEqual(kwargs["max_retries"], 0)
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["base_url"], "https://api.openai.com/v1")
        sdk.DefaultAsyncHttpxClient.assert_called_once_with(timeout=30.0, follow_redirects=False, trust_env=False)
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["max_completion_tokens"], 123)
        self.assertEqual(call["messages"], [{"role": "user", "content": "prompt"}])
        self.assertEqual(model.request_count, 1)
        await model.aclose()
        client.close.assert_awaited_once()

    async def test_azure_sdk_receives_deployment_and_explicit_configuration(self):
        client = fake_sdk_client()
        sdk = types.SimpleNamespace(AsyncAzureOpenAI=Mock(return_value=client), DefaultAsyncHttpxClient=Mock())
        with patch("sage.providers.importlib.import_module", return_value=sdk):
            model = OpenAIModel.from_env(env={"MAIN_LLM_MODEL": "deployment", "is_azure": "true",
                "AZURE_OPENAI_KEY": SECRET, "AZURE_OPENAI_ENDPOINT": "https://azure.test",
                "AZURE_OPENAI_API_VERSION": "version"})
            await model.complete("stage", "prompt", max_tokens=10)
        self.assertEqual(sdk.AsyncAzureOpenAI.call_args.kwargs["max_retries"], 0)
        self.assertEqual(sdk.AsyncAzureOpenAI.call_args.kwargs["azure_endpoint"], "https://azure.test")
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "deployment")

    async def test_new_sdk_transport_name_disables_redirects(self):
        client = fake_sdk_client()
        sdk = types.SimpleNamespace(AsyncOpenAI=Mock(return_value=client), DefaultAsyncHttpx2Client=Mock())
        with patch("sage.providers.importlib.import_module", return_value=sdk):
            await self.model().complete("stage", "prompt", max_tokens=10)
        sdk.DefaultAsyncHttpx2Client.assert_called_once_with(timeout=30.0, follow_redirects=False, trust_env=False)

    async def test_missing_sdk_and_failed_initialization_sanitized(self):
        with patch("sage.providers.importlib.import_module", side_effect=ImportError(SECRET)):
            with self.assertRaises(ConfigurationError) as caught:
                await self.model().complete("stage", "prompt", max_tokens=10)
        self.assertNotIn(SECRET, str(caught.exception))
        sdk = types.SimpleNamespace(AsyncOpenAI=Mock(side_effect=ValueError(SECRET)))
        with patch("sage.providers.importlib.import_module", return_value=sdk):
            with self.assertRaises(ConfigurationError) as caught:
                await self.model().complete("stage", "prompt", max_tokens=10)
        self.assertNotIn(SECRET, str(caught.exception))

    async def test_transient_statuses_are_single_attempts(self):
        for status in (408, 409, 429, 500, 503):
            client = fake_sdk_client(error=StatusError(status))
            model = self.model(client)
            with self.subTest(status=status), self.assertRaises(TransientProviderError) as caught:
                await model.complete("stage", "prompt", max_tokens=10)
            client.chat.completions.create.assert_awaited_once()
            self.assertEqual(model.request_count, 1)
            self.assertNotIn(SECRET, str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

    async def test_authentication_and_bad_request_are_permanent(self):
        for status in (400, 401, 403, 404):
            client = fake_sdk_client(error=StatusError(status))
            with self.subTest(status=status), self.assertRaises(ProviderError) as caught:
                await self.model(client).complete("stage", "prompt", max_tokens=10)
            self.assertNotIsInstance(caught.exception, TransientProviderError)
            self.assertNotIn(SECRET, str(caught.exception))
            client.chat.completions.create.assert_awaited_once()

    async def test_sdk_timeout_connection_errors_sanitized(self):
        for name in ("APITimeoutError", "APIConnectionError"):
            error = type(name, (Exception,), {})(SECRET)
            client = fake_sdk_client(error=error)
            with self.subTest(name=name), self.assertRaises(TransientProviderError) as caught:
                await self.model(client).complete("stage", "prompt", max_tokens=10)
            self.assertNotIn(SECRET, str(caught.exception))

    async def test_adapter_timeout_and_cancellation(self):
        async def delayed(**kwargs):
            await asyncio.sleep(10)
        client = fake_sdk_client()
        client.chat.completions.create.side_effect = delayed
        with self.assertRaises(TransientProviderError):
            await self.model(client, timeout=0.01).complete("stage", "prompt", max_tokens=10)
        client.chat.completions.create.assert_awaited_once()
        client = fake_sdk_client(error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await self.model(client).complete("stage", "prompt", max_tokens=10)

    async def test_malformed_empty_refused_and_truncated_completions(self):
        invalid = [object(), types.SimpleNamespace(choices=[]), sdk_reply(""), sdk_reply("   "),
                   sdk_reply(None), sdk_reply(["text"]), sdk_reply("partial", reason="length"),
                   sdk_reply("blocked", reason="content_filter"), sdk_reply("text", reason={}),
                   sdk_reply("x" * 1_000_001)]
        refused = sdk_reply("text")
        refused.choices[0].message.refusal = "provider refusal"
        invalid.append(refused)
        for reply in invalid:
            with self.subTest(reply_type=type(reply).__name__), self.assertRaises(InvalidResponse):
                await self.model(fake_sdk_client(reply=reply)).complete("stage", "prompt", max_tokens=10)

    async def test_invalid_input_never_calls_provider(self):
        client = fake_sdk_client()
        model = self.model(client)
        for tokens in (0, -1, 65_537, True, "100"):
            with self.subTest(tokens=tokens), self.assertRaises(ConfigurationError):
                await model.complete("stage", "prompt", max_tokens=tokens)
        for prompt in (None, "", " ", "x" * 250_001):
            with self.subTest(prompt_type=type(prompt).__name__), self.assertRaises(ConfigurationError):
                await model.complete("stage", prompt, max_tokens=10)
        client.chat.completions.create.assert_not_called()

    async def test_embedding_order_vectors_and_single_attempt(self):
        client = fake_sdk_client()
        client.embeddings.create.return_value = types.SimpleNamespace(data=[
            types.SimpleNamespace(index=1, embedding=[0, 1]), types.SimpleNamespace(index=0, embedding=[1, 0])])
        model = self.model(client)
        self.assertEqual(await model.embed(["one", "two"]), [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(model.request_count, 1)
        self.assertEqual(client.embeddings.create.call_args.kwargs["model"], "embed-model")
        client.embeddings.create.assert_awaited_once()

    async def test_embedding_disabled_and_invalid_inputs(self):
        model = OpenAIModel.from_env(env={"MAIN_LLM_MODEL": "main", "OPENAI_API_KEY": SECRET}, client=fake_sdk_client())
        with self.assertRaises(ConfigurationError):
            await model.embed(["text"])
        model = self.model(fake_sdk_client())
        for value in ([], "text", [""], ["x" * 16_001], ["text"] * 102, [None], ["x" * 16_000] * 20):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ConfigurationError):
                await model.embed(value)
        self.assertEqual(model.request_count, 0)

    async def test_embedding_malformed_vectors_and_rate_limit(self):
        vectors = ([], [0, 0], [math.nan], [math.inf], [True], ["1"], [1.0] * 8193)
        for vector in vectors:
            client = fake_sdk_client()
            client.embeddings.create.return_value = types.SimpleNamespace(data=[types.SimpleNamespace(index=0, embedding=vector)])
            with self.subTest(length=len(vector)), self.assertRaises(InvalidResponse):
                await self.model(client).embed(["text"])
        for items in ([types.SimpleNamespace(index=1, embedding=[1])], [],
                      [types.SimpleNamespace(index=0, embedding=[1]), types.SimpleNamespace(index=0, embedding=[1])]):
            client = fake_sdk_client()
            client.embeddings.create.return_value = types.SimpleNamespace(data=items)
            with self.assertRaises(InvalidResponse):
                await self.model(client).embed(["text"])
        client = fake_sdk_client()
        client.embeddings.create.side_effect = StatusError(429)
        with self.assertRaises(TransientProviderError) as caught:
            await self.model(client).embed(["text"])
        self.assertNotIn(SECRET, str(caught.exception))
        client.embeddings.create.assert_awaited_once()

    async def test_separate_embedding_client_is_azure_and_has_no_retries(self):
        client = fake_sdk_client()
        client.embeddings.create.return_value = types.SimpleNamespace(data=[types.SimpleNamespace(index=0, embedding=[1])])
        sdk = types.SimpleNamespace(AsyncAzureOpenAI=Mock(return_value=client), DefaultAsyncHttpxClient=Mock())
        model = OpenAIModel.from_env(env={"MAIN_LLM_MODEL": "main", "OPENAI_API_KEY": SECRET,
            "EMBEDDING_MODEL": "embedding", "EMBEDDING_API_ENDPOINT": "https://embedding.azure.test",
            "EMBEDDING_API_KEY": SECRET, "AZURE_OPENAI_API_VERSION": "version"})
        with patch("sage.providers.importlib.import_module", return_value=sdk):
            await model.embed(["text"])
        self.assertEqual(sdk.AsyncAzureOpenAI.call_args.kwargs["max_retries"], 0)
        self.assertEqual(sdk.AsyncAzureOpenAI.call_args.kwargs["azure_endpoint"], "https://embedding.azure.test")


class ScholarTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_maps_metadata_and_sends_bounded_official_request(self):
        transport = FakeTransport(http_reply([record(title="  A  title\n here ", abstract=None,
                    year="2023", citationCount="42", publicationDate="2023-04-05", url="javascript:unsafe")]))
        source = SemanticScholarSource.from_env(env={"SEMENTIC_SEARCH_API_KEY": SECRET}, transport=transport)
        papers = await source.search("query & more", limit=3, publication_date="2020:2024")
        self.assertEqual(papers[0].title, "A title here")
        self.assertEqual(papers[0].abstract, "")
        self.assertEqual(papers[0].year, 2023)
        self.assertEqual(papers[0].publication_date, "2023-04-05")
        self.assertEqual(papers[0].citation_count, 42)
        self.assertEqual(papers[0].evidence_scope, "abstract_only")
        self.assertIsNone(papers[0].article)
        self.assertEqual(papers[0].url, "https://www.semanticscholar.org/paper/paper-1")
        url, headers, timeout, byte_limit = transport.calls[0]
        parts = urlsplit(url)
        self.assertEqual(parts.netloc, "api.semanticscholar.org")
        self.assertEqual(parts.path, "/graph/v1/paper/search")
        self.assertEqual(parse_qs(parts.query)["query"], ["query & more"])
        self.assertEqual(parse_qs(parts.query)["publicationDateOrYear"], ["2020:2024"])
        self.assertEqual(headers["x-api-key"], SECRET)
        self.assertEqual((timeout, byte_limit), (20.0, 2_000_000))
        self.assertEqual(source.request_count, 1)

    async def test_invalid_date_precision_is_not_invented(self):
        for value in (None, "2024", "2024-02", "2024-02-30", "2023-02-29", [], 2024):
            transport = FakeTransport(http_reply([record(publicationDate=value)]))
            paper = (await SemanticScholarSource(transport=transport).search("query", limit=1))[0]
            self.assertIsNone(paper.publication_date)

    async def test_huge_optional_integer_is_ignored_without_conversion_error(self):
        transport = FakeTransport(http_reply([record(year="9" * 5000, citationCount="9" * 5000)]))
        paper = (await SemanticScholarSource(transport=transport).search("query", limit=1))[0]
        self.assertIsNone(paper.year)
        self.assertEqual(paper.citation_count, 0)

    async def test_missing_optional_metadata_and_empty_results(self):
        transport = FakeTransport(http_reply([record(year=True, citationCount=-10)]), http_reply([]))
        source = SemanticScholarSource(transport=transport)
        paper = (await source.search("query", limit=5))[0]
        self.assertIsNone(paper.year)
        self.assertEqual(paper.citation_count, 0)
        self.assertEqual(await source.search("query", limit=5), [])
        self.assertNotIn("x-api-key", transport.calls[0][1])

    async def test_deduplicates_ids_and_enforces_result_limit(self):
        transport = FakeTransport(http_reply([record(), record(), record("paper-2"), record("paper-3")]))
        result = await SemanticScholarSource(transport=transport).search("query", limit=3)
        self.assertEqual([paper.paper_id for paper in result], ["paper-1", "paper-2"])

    async def test_relationship_uses_stable_id_and_direction(self):
        for direction, endpoint, nested in (("forward", "citations", "citingPaper"),
                                             ("backward", "references", "citedPaper")):
            transport = FakeTransport(http_reply([{nested: record("related")}]))
            source = SemanticScholarSource(transport=transport)
            result = await source.related(Paper(paper_id="DOI:10.1000/example", title="Do not search title"), direction=direction, limit=2)
            self.assertEqual(result[0].paper_id, "related")
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(urlsplit(transport.calls[0][0]).path,
                             "/graph/v1/paper/DOI%3A10.1000%2Fexample/" + endpoint)

    async def test_missing_id_title_fallback_is_single_request_and_exact(self):
        transport = FakeTransport(http_reply([record(title=" A TITLE ", citations=[record("related")])]))
        source = SemanticScholarSource(transport=transport)
        papers = await source.related(Paper(paper_id="", title="A title"), direction="forward", limit=2)
        self.assertEqual(papers[0].paper_id, "related")
        self.assertEqual(source.request_count, 1)
        self.assertEqual(urlsplit(transport.calls[0][0]).path, "/graph/v1/paper/search/match")
        fields = parse_qs(urlsplit(transport.calls[0][0]).query)["fields"][0]
        self.assertIn("citations.paperId", fields)

    async def test_title_fallback_refuses_fuzzy_ambiguous_or_wrong_year(self):
        for values in ([record(title="Different title", references=[])],
                       [record(title="A title", references=[]), record("another", title="A title", references=[])],
                       [record(title="A title", year=2010, references=[])],
                       [record(title="A title")]):
            transport = FakeTransport(http_reply(values))
            with self.subTest(count=len(values)), self.assertRaises(InvalidResponse):
                await SemanticScholarSource(transport=transport).related(Paper("", "A title", year=2024), direction="backward", limit=2)
            self.assertEqual(len(transport.calls), 1)

    async def test_null_related_paper_is_omitted(self):
        transport = FakeTransport(http_reply([{"citingPaper": None}, {"citingPaper": record("related")}]))
        papers = await SemanticScholarSource(transport=transport).related(Paper("id", "title"), direction="forward", limit=2)
        self.assertEqual([paper.paper_id for paper in papers], ["related"])

    async def test_rate_limits_and_server_failures_do_not_retry(self):
        for status in (429, 500, 503, 408):
            transport = FakeTransport(HTTPResponse(status, SECRET.encode()))
            source = SemanticScholarSource(transport=transport)
            with self.subTest(status=status), self.assertRaises(TransientProviderError) as caught:
                await source.search("query", limit=1)
            self.assertEqual(source.request_count, 1)
            self.assertEqual(len(transport.calls), 1)
            self.assertNotIn(SECRET, str(caught.exception))

    async def test_auth_errors_and_redirects_are_permanent(self):
        for status in (301, 302, 400, 401, 403, 404):
            transport = FakeTransport(HTTPResponse(status, SECRET.encode()))
            with self.subTest(status=status), self.assertRaises(ProviderError) as caught:
                await SemanticScholarSource(transport=transport).search("query", limit=1)
            self.assertNotIsInstance(caught.exception, TransientProviderError)
            self.assertNotIn(SECRET, str(caught.exception))
            self.assertEqual(len(transport.calls), 1)

    async def test_transport_runs_off_event_loop_and_has_outer_timeout(self):
        transport = FakeTransport(http_reply([]))
        with patch("sage.providers.asyncio.to_thread", new_callable=AsyncMock, return_value=http_reply([])) as offload:
            self.assertEqual(await SemanticScholarSource(transport=transport).search("query", limit=1), [])
        offload.assert_awaited_once()
        self.assertIs(offload.call_args.args[0], transport)
        async def stalled(*args, **kwargs):
            await asyncio.sleep(10)
        with patch("sage.providers.asyncio.to_thread", side_effect=stalled):
            with self.assertRaises(TransientProviderError):
                await SemanticScholarSource(timeout=0.01, transport=transport).search("query", limit=1)

    async def test_network_timeout_sanitized(self):
        transport = FakeTransport(TimeoutError(SECRET))
        with self.assertRaises(TransientProviderError) as caught:
            await SemanticScholarSource(transport=transport).search("query", limit=1)
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual(len(transport.calls), 1)

    async def test_malformed_json_envelopes_and_size_caps(self):
        bodies = (b"not json", b"\xff", b"[]", b"{}", b'{"data": {}}', b'{"error": "secret"}')
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(InvalidResponse):
                await SemanticScholarSource(transport=FakeTransport(HTTPResponse(200, body))).search("query", limit=1)
        with self.assertRaises(InvalidResponse):
            await SemanticScholarSource(max_response_bytes=10, transport=FakeTransport(http_reply([record()]))).search("query", limit=1)

    async def test_invalid_records_never_become_fabricated_papers(self):
        records = (None, {}, record(paperId=""), record(title=""), record(abstract=["not text"]), record(abstract=[]),
                   record(paperId="contains\nnewline"))
        for value in records:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(InvalidResponse):
                await SemanticScholarSource(transport=FakeTransport(http_reply([value]))).search("query", limit=1)
        with self.assertRaises(InvalidResponse):
            await SemanticScholarSource(transport=FakeTransport(http_reply([{}]))).related(Paper("id", "title"), direction="forward", limit=1)

    async def test_invalid_inputs_make_no_requests(self):
        transport = FakeTransport()
        source = SemanticScholarSource(transport=transport)
        for limit in (0, -1, 101, True, "3"):
            with self.subTest(limit=limit), self.assertRaises(ConfigurationError):
                await source.search("query", limit=limit)
        for query in ("", " ", None, "x" * 4097):
            with self.subTest(query_type=type(query).__name__), self.assertRaises(ConfigurationError):
                await source.search(query, limit=1)
        with self.assertRaises(ConfigurationError):
            await source.search("query", limit=1, publication_date="invalid")
        with self.assertRaises(ConfigurationError):
            await source.related(Paper("id", "title"), direction="invalid", limit=1)
        self.assertEqual(source.request_count, 0)
        self.assertEqual(transport.calls, [])


class HTTPTransportTests(unittest.TestCase):
    def connection(self, response):
        connection = Mock()
        connection.getresponse.return_value = response
        return connection

    def test_official_host_only(self):
        for url in ("https://evil.test/graph/v1/paper/search", "http://api.semanticscholar.org/graph/v1/paper/search",
                    "https://api.semanticscholar.org@evil.test/graph/v1/paper/search"):
            with self.subTest(url=url), self.assertRaises(ConfigurationError):
                _https_request(url, {}, 1, 1000)

    def test_bounded_reads_connection_close_and_no_redirect_follow(self):
        response = Mock(status=200)
        response.getheader.return_value = "4"
        response.read1.side_effect = [b"data", b""]
        connection = self.connection(response)
        with patch("sage.providers.http.client.HTTPSConnection", return_value=connection) as factory:
            result = _https_request("https://api.semanticscholar.org/graph/v1/paper/search?query=one", {}, 10, 100)
        self.assertEqual(result.body, b"data")
        self.assertEqual(factory.call_args.args, ("api.semanticscholar.org",))
        connection.close.assert_called_once()
        self.assertLessEqual(response.read1.call_args.args[0], 101)
        response = Mock(status=302)
        connection = self.connection(response)
        with patch("sage.providers.http.client.HTTPSConnection", return_value=connection):
            self.assertEqual(_https_request("https://api.semanticscholar.org/graph/v1/paper/search", {}, 10, 100).status, 302)
        response.read1.assert_not_called()
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    def test_expired_read_deadline_closes_connection(self):
        response = Mock(status=200)
        connection = self.connection(response)
        with patch("sage.providers.http.client.HTTPSConnection", return_value=connection), \
             patch("sage.providers.time.monotonic", side_effect=[0, 11]):
            with self.assertRaises(TimeoutError):
                _https_request("https://api.semanticscholar.org/graph/v1/paper/search", {}, 10, 100)
        connection.close.assert_called_once()
        connection.request.assert_not_called()

    def test_declared_and_actual_size_rejected(self):
        for length, chunks in (("1001", []), (None, [b"x" * 101])):
            response = Mock(status=200)
            response.getheader.return_value = length
            response.read1.side_effect = chunks
            connection = self.connection(response)
            with patch("sage.providers.http.client.HTTPSConnection", return_value=connection):
                with self.assertRaises(InvalidResponse):
                    _https_request("https://api.semanticscholar.org/graph/v1/paper/search", {}, 10, 100)
            connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
