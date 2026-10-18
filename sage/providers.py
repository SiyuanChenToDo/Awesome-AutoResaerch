# MODIFIED for SAGE, 2026-10-17: owned, bounded async provider adapters;
# replaces upstream unbounded retries, blocking async I/O, and raw error logging.
# Derived from DAMO-NLP-SG/CoI-Agent LLM.py and searcher/sementic_search.py,
# commit ac94317ff2d1997f362747edc2c9e5f0fdc9c450, Apache-2.0.
# License: ../LICENSES/CoI-Agent-Apache-2.0.txt; attribution: ../NOTICE.md.
"""Opt-in live providers. Importing this module never imports the SDK or calls APIs.

Each transport attempt has a timeout and no adapter/SDK retries. The caller owns
retry and aggregate budgets. Paper metadata/abstracts are not full-text evidence.
Source APIs: https://github.com/openai/openai-python and
https://api.semanticscholar.org/api-docs/ .
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import partial
import http.client
import importlib
import json
import math
import os
import re
import socket
import ssl
import time
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from .errors import ConfigurationError, InvalidResponse, ProviderError, TransientProviderError
from .types import Paper

_GRAPH_ROOT = "https://api.semanticscholar.org/graph/v1"
_PAPER_FIELDS = "paperId,title,abstract,year,url,citationCount,publicationDate"
_TRANSIENT_STATUSES = {408, 409, 425, 429}


def parse_bool(value: object, *, name: str = "boolean setting") -> bool:
    """Parse explicit booleans; importantly, the string 'False' is false."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ConfigurationError(f"{name} must be true or false")


def _setting(env: Mapping[str, str], *names: str, default: str | None = None) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None:
            if not isinstance(value, str):
                raise ConfigurationError(f"{name} must be a string")
            if value.strip():
                return value.strip()
    return default


def _required(env: Mapping[str, str], *names: str) -> str:
    value = _setting(env, *names)
    if value is None:
        raise ConfigurationError(f"Missing configuration: {' or '.join(names)}")
    return value


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 300:
        raise ConfigurationError("Provider timeout must be greater than 0 and at most 300 seconds")
    return float(value)


def _https_endpoint(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == "https" and bool(parts.hostname) and parts.username is None
                 and parts.password is None and not parts.query and not parts.fragment
                 and not any(ord(char) < 33 for char in value))
        _ = parts.port
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ConfigurationError(f"{name} must be an HTTPS URL without credentials, query, or fragment")
    return value


def _proxy_url(value: str | None) -> str | None:
    """Only credential-free HTTP CONNECT proxies; origin TLS stays verified."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError("Environment proxy must be a credential-free HTTP CONNECT URL")
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == "http" and bool(parts.hostname)
                 and parts.username is None and parts.password is None
                 and parts.path in {"", "/"} and not parts.query and not parts.fragment
                 and not any(ord(char) < 33 or ord(char) == 127 for char in value))
        port = parts.port
        valid = valid and (port is None or 1 <= port <= 65535)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ConfigurationError("Environment proxy must be a credential-free HTTP CONNECT URL")
    return value


def _environment_proxy(env: Mapping[str, str]) -> str | None:
    # Explicit consent avoids silently forwarding secrets via ambient proxies.
    # Do not honor NO_PROXY: opt-in must never silently fall back to direct IO.
    if not parse_bool(_setting(env, "SAGE_USE_ENV_PROXY", default="false"),
                      name="SAGE_USE_ENV_PROXY"):
        return None
    upper = _setting(env, "HTTPS_PROXY")
    lower = _setting(env, "https_proxy")
    if upper and lower and upper != lower:
        raise ConfigurationError("Conflicting HTTPS_PROXY and https_proxy settings")
    value = upper or lower
    if value is None:
        raise ConfigurationError("SAGE_USE_ENV_PROXY requires HTTPS_PROXY or https_proxy")
    return _proxy_url(value)


def _provider_error(error: Exception, provider: str) -> ProviderError:
    """Never interpolate provider bodies, URLs, prompts, or credentials."""
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        if status in _TRANSIENT_STATUSES or 500 <= status <= 599:
            return TransientProviderError(f"{provider} temporarily unavailable (HTTP {status})")
        return ProviderError(f"{provider} request rejected (HTTP {status})")
    names = {cls.__name__ for cls in type(error).__mro__}
    if isinstance(error, ssl.SSLCertVerificationError):
        return ProviderError(f"{provider} TLS certificate verification failed")
    if isinstance(error, (TimeoutError, socket.timeout)) or names & {"APITimeoutError", "ReadTimeout", "ConnectTimeout"}:
        return TransientProviderError(f"{provider} request timed out")
    if isinstance(error, (ConnectionError, OSError, http.client.HTTPException)) or names & {"APIConnectionError", "ConnectError"}:
        return TransientProviderError(f"{provider} connection failed")
    return ProviderError(f"{provider} request failed")


@dataclass(frozen=True)
class OpenAIConfig:
    model: str
    is_azure: bool = False
    api_key: str = field(default="", repr=False)
    endpoint: str | None = field(default=None, repr=False)
    api_version: str | None = None
    embedding_model: str | None = None
    embedding_endpoint: str | None = field(default=None, repr=False)
    embedding_api_key: str | None = field(default=None, repr=False)
    embedding_api_version: str | None = None
    provider: str = "openai"
    deepseek_thinking: str = "disabled"
    proxy_url: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _proxy_url(self.proxy_url)
        if self.provider not in ("openai", "deepseek"):
            raise ConfigurationError("SAGE_MODEL_PROVIDER must be openai or deepseek")
        if self.deepseek_thinking not in ("enabled", "disabled"):
            raise ConfigurationError("SAGE_DEEPSEEK_THINKING must be enabled or disabled")
        if self.provider == "deepseek" and self.is_azure:
            raise ConfigurationError("DeepSeek provider cannot use Azure configuration")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 256:
            raise ConfigurationError("Model/deployment name must contain 1 to 256 characters")
        if not isinstance(self.is_azure, bool):
            raise ConfigurationError("is_azure must be a parsed boolean")
        if not isinstance(self.api_key, str) or not self.api_key.strip() or any(ord(char) < 32 for char in self.api_key):
            raise ConfigurationError("Model API key is missing or invalid")
        _https_endpoint(self.endpoint, "Model endpoint")
        _https_endpoint(self.embedding_endpoint, "Embedding endpoint")
        if self.is_azure and (not self.endpoint or not self.api_version):
            raise ConfigurationError("Azure requires an endpoint and API version")
        if self.embedding_model is not None and (not isinstance(self.embedding_model, str)
                or not self.embedding_model.strip() or len(self.embedding_model) > 256):
            raise ConfigurationError("Embedding model/deployment name must contain 1 to 256 characters")
        if self.embedding_endpoint and (not self.embedding_model or not self.embedding_api_key or not self.embedding_api_version):
            raise ConfigurationError("Separate Azure embeddings require model, key, and API version")

    @classmethod
    def from_env(cls, *, role: str = "main", env: Mapping[str, str] | None = None) -> "OpenAIConfig":
        env = os.environ if env is None else env
        if role not in {"main", "cheap"}:
            raise ConfigurationError("Model role must be main or cheap")
        provider = _setting(env, "SAGE_MODEL_PROVIDER", default="openai")
        thinking = _setting(env, "SAGE_DEEPSEEK_THINKING", default="disabled")
        is_azure = parse_bool(_setting(env, "SAGE_IS_AZURE", "is_azure", default="false"), name="SAGE_IS_AZURE/is_azure")
        if provider == "deepseek" and is_azure:
            raise ConfigurationError("DeepSeek provider cannot use Azure configuration")
        model = _required(env, f"SAGE_{role.upper()}_MODEL", f"SAGE_{role.upper()}_LLM_MODEL", f"{role.upper()}_LLM_MODEL")
        if is_azure:
            key = _required(env, "SAGE_AZURE_OPENAI_KEY", "SAGE_AZURE_OPENAI_API_KEY", "AZURE_OPENAI_KEY", "AZURE_OPENAI_API_KEY")
            endpoint = _https_endpoint(_required(env, "SAGE_AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_ENDPOINT"), "AZURE_OPENAI_ENDPOINT")
            version = _required(env, "SAGE_AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_API_VERSION", "OPENAI_API_VERSION")
        else:
            key = _required(env, "SAGE_OPENAI_API_KEY", "OPENAI_API_KEY")
            endpoint = _https_endpoint(_setting(env, "SAGE_OPENAI_BASE_URL", "OPENAI_BASE_URL"), "OPENAI_BASE_URL")
            version = None
        embedding_model = _setting(env, "SAGE_EMBEDDING_MODEL", "EMBEDDING_MODEL")
        embedding_endpoint = _https_endpoint(_setting(env, "SAGE_EMBEDDING_API_ENDPOINT", "EMBEDDING_API_ENDPOINT"), "EMBEDDING_API_ENDPOINT")
        embedding_key = None
        embedding_version = None
        if embedding_endpoint:
            if not embedding_model:
                raise ConfigurationError("Missing configuration: SAGE_EMBEDDING_MODEL or EMBEDDING_MODEL")
            embedding_key = _required(env, "SAGE_EMBEDDING_API_KEY", "EMBEDDING_API_KEY")
            embedding_version = _required(env, "SAGE_EMBEDDING_API_VERSION", "SAGE_AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_API_VERSION", "OPENAI_API_VERSION")
        return cls(model=model, is_azure=is_azure, api_key=key, endpoint=endpoint,
                   api_version=version, embedding_model=embedding_model,
                   embedding_endpoint=embedding_endpoint, embedding_api_key=embedding_key,
                   embedding_api_version=embedding_version, provider=provider, deepseek_thinking=thinking,
                   proxy_url=_environment_proxy(env))


class OpenAIModel:
    """OpenAI/Azure chat and optional embeddings, with one attempt per method call.

    Supply an SDK-shaped async client in tests. No package is required until the
    first real request. Call aclose() on live clients after the workflow ends.
    """

    def __init__(self, config: OpenAIConfig, *, timeout: float = 30.0, client: Any = None,
                 embedding_client: Any = None) -> None:
        self.config = config
        self.timeout = _timeout(timeout)
        self._client = client
        self._embedding_client = embedding_client
        self._owns_client = client is None
        self._owns_embedding_client = embedding_client is None
        self.request_count = 0

    @classmethod
    def from_env(cls, *, role: str = "main", env: Mapping[str, str] | None = None,
                 timeout: float = 30.0, client: Any = None, embedding_client: Any = None) -> "OpenAIModel":
        return cls(OpenAIConfig.from_env(role=role, env=env), timeout=timeout,
                   client=client, embedding_client=embedding_client)

    @property
    def embedding_enabled(self) -> bool:
        return bool(self.config.embedding_model)

    def _make_client(self, *, embeddings: bool = False) -> Any:
        try:
            sdk = importlib.import_module("openai")
        except ImportError:
            raise ConfigurationError("Live model requests require the optional openai package") from None
        except Exception:
            raise ConfigurationError("Could not load the optional model SDK") from None
        separate = embeddings and self.config.embedding_endpoint is not None
        kwargs: dict[str, Any] = {"timeout": self.timeout, "max_retries": 0}
        if separate or self.config.is_azure:
            kwargs.update(api_key=self.config.embedding_api_key if separate else self.config.api_key,
                          azure_endpoint=self.config.embedding_endpoint if separate else self.config.endpoint,
                          api_version=self.config.embedding_api_version if separate else self.config.api_version)
            factory = sdk.AsyncAzureOpenAI
        else:
            # Explicit base_url avoids a second, unvalidated environment lookup in the SDK.
            kwargs.update(api_key=self.config.api_key,
                          base_url=self.config.endpoint or ("https://api.deepseek.com"
                              if self.config.provider == "deepseek" else "https://api.openai.com/v1"))
            factory = sdk.AsyncOpenAI
        try:
            # SDK defaults may follow redirects. Disable them so credentials and
            # one-attempt accounting remain at the configured destination.
            transport_factory = (getattr(sdk, "DefaultAsyncHttpx2Client", None)
                                 or getattr(sdk, "DefaultAsyncHttpxClient", None))
            if transport_factory is None:
                raise ValueError
            proxy_options = {"proxy": self.config.proxy_url} if self.config.proxy_url else {}
            kwargs["http_client"] = transport_factory(
                timeout=self.timeout, follow_redirects=False, trust_env=False, **proxy_options)
            return factory(**kwargs)
        except Exception:
            raise ConfigurationError("Could not initialize the configured model client") from None

    def _get_client(self, *, embeddings: bool = False) -> Any:
        if embeddings and (self._embedding_client is not None or self.config.embedding_endpoint):
            if self._embedding_client is None:
                self._embedding_client = self._make_client(embeddings=True)
            return self._embedding_client
        if self._client is None:
            self._client = self._make_client()
        return self._client

    async def complete(self, stage: str, prompt: str, *, max_tokens: int) -> str:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1_000_000:
            raise ConfigurationError("Model prompt must contain 1 to 1000000 characters")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 65_536:
            raise ConfigurationError("max_tokens must be an integer from 1 to 65536")
        client = self._get_client()
        self.request_count += 1
        # Select the wire contract explicitly, never by guessing from the hostname.
        # DeepSeek documents max_tokens; max_completion_tokens is not its contract.
        output_options = ({"max_tokens": max_tokens,
                           "extra_body": {"thinking": {"type": self.config.deepseek_thinking}}}
                          if self.config.provider == "deepseek"
                          else {"max_completion_tokens": max_tokens})
        try:
            reply = await asyncio.wait_for(client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
                **output_options,
                timeout=self.timeout,
            ), timeout=self.timeout)
        except Exception as error:
            raise _provider_error(error, "Model provider") from None
        try:
            usage = getattr(reply, 'usage', None)
            self.last_response_model = getattr(reply, 'model', None)
            self.last_response_id = getattr(reply, 'id', None)
            for name in ('last_response_model', 'last_response_id'):
                value = getattr(self, name)
                if not isinstance(value, str) or len(value) > 200 or not re.fullmatch(r'[A-Za-z0-9_./:@+\-]+', value):
                    setattr(self, name, None)
            self.last_usage = {key: getattr(usage, key, None) for key in
                               ('prompt_tokens', 'completion_tokens', 'total_tokens')}
            choice = reply.choices[0]
            content = choice.message.content
            finish_reason = getattr(choice, "finish_reason", None)
            refusal = getattr(choice.message, "refusal", None)
        except (AttributeError, IndexError, TypeError):
            raise InvalidResponse("Model provider returned an invalid completion") from None
        if finish_reason == "length":
            from .errors import TruncatedResponse
            error = TruncatedResponse("Model completion reached output limit")
            # Private checkpoint retention is opt-in at Runtime. Never log this
            # text or promote an incomplete answer to a validated result.
            error.partial_response = content if isinstance(content, str) else None
            raise error
        if refusal or (finish_reason is not None and finish_reason != "stop"):
            raise InvalidResponse("Model provider returned a refused, incomplete, or non-text completion")
        if not isinstance(content, str) or not content.strip() or len(content) > 1_000_000:
            raise InvalidResponse("Model provider returned empty or invalid completion text")
        return content.strip()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One bounded embedding request; caller must count it in the API budget."""
        if not self.embedding_enabled:
            raise ConfigurationError("Embedding ranking requires SAGE_EMBEDDING_MODEL or EMBEDDING_MODEL")
        if (not isinstance(texts, list) or not 1 <= len(texts) <= 101
                or any(not isinstance(text, str) or not text.strip() or len(text) > 16_000 for text in texts)
                or sum(map(len, texts)) > 250_000):
            raise ConfigurationError("Embedding input exceeds bounded text batch limits")
        client = self._get_client(embeddings=True)
        self.request_count += 1
        try:
            reply = await asyncio.wait_for(client.embeddings.create(
                model=self.config.embedding_model, input=texts,
                encoding_format="float", timeout=self.timeout,
            ), timeout=self.timeout)
        except Exception as error:
            raise _provider_error(error, "Embedding provider") from None
        try:
            data = reply.data
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError
            indexed: dict[int, list[float]] = {}
            dimensions = None
            for item in data:
                index, vector = item.index, item.embedding
                if type(index) is not int or not 0 <= index < len(texts) or index in indexed:
                    raise ValueError
                if not isinstance(vector, list) or not 1 <= len(vector) <= 8192:
                    raise ValueError
                if dimensions is not None and dimensions != len(vector):
                    raise ValueError
                dimensions = len(vector)
                if any(type(value) not in {int, float} or not math.isfinite(value) for value in vector):
                    raise ValueError
                if not any(vector):
                    raise ValueError
                indexed[index] = [float(value) for value in vector]
            return [indexed[index] for index in range(len(texts))]
        except (AttributeError, TypeError, ValueError, OverflowError, KeyError):
            raise InvalidResponse("Embedding provider returned invalid vectors") from None

    async def aclose(self) -> None:
        for client, owned in ((self._client, self._owns_client),
                              (self._embedding_client, self._owns_embedding_client)):
            if client is not None and owned:
                try:
                    await asyncio.wait_for(client.close(), timeout=self.timeout)
                except Exception:
                    raise ProviderError("Model client cleanup failed") from None


@dataclass(frozen=True)
class HTTPResponse:
    """Injected transport result. Never store or log raw non-success bodies."""
    status: int
    body: bytes = field(repr=False)
    retry_after_seconds: float | None = None


def _retry_after(value):
    """Preserve bounded header metadata, never response bodies or credential headers."""
    if not isinstance(value, str) or len(value) > 100:
        return None
    try:
        seconds = float(value) if value.strip().isdigit() else None
        if seconds is None:
            from email.utils import parsedate_to_datetime
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except (ValueError, TypeError, OverflowError):
        return None


Transport = Callable[[str, Mapping[str, str], float, int], HTTPResponse]


def _https_request(url: str, headers: Mapping[str, str], timeout: float, max_bytes: int,
                   *, proxy_url: str | None = None) -> HTTPResponse:
    """One verified-TLS GET, optional CONNECT, no redirects, bounded body/deadline."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "api.semanticscholar.org" or not parts.path.startswith("/graph/v1/"):
        raise ConfigurationError("Paper requests must use the official Semantic Scholar graph API")
    return _metadata_https_request(url, headers, timeout, max_bytes, proxy_url=proxy_url)


def _metadata_https_request(url: str, headers: Mapping[str, str], timeout: float, max_bytes: int,
                            *, proxy_url: str | None = None) -> HTTPResponse:
    """Shared bounded transport; only two fixed metadata endpoints are allowed."""
    parts = urlsplit(url)
    article_endpoint = (parts.netloc == 'arxiv.org' and not parts.query and
                        re.fullmatch(r'/(?:html|pdf)/(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z.\-]+/\d{7})(?:v[1-9]\d*)?', parts.path))
    allowed = ((parts.netloc == "api.semanticscholar.org" and parts.path.startswith("/graph/v1/"))
               or (parts.netloc == "export.arxiv.org" and parts.path == "/api/query") or article_endpoint)
    if parts.scheme != "https" or not allowed or parts.fragment:
        raise ConfigurationError("Unapproved paper metadata endpoint")
    if parts.netloc in ("export.arxiv.org", "arxiv.org") and any(k.lower() not in {"accept", "user-agent"} for k in headers):
        raise ConfigurationError("arXiv metadata transport does not accept credential headers")
    deadline = time.monotonic() + timeout
    proxy_url = _proxy_url(proxy_url)
    if proxy_url:
        proxy = urlsplit(proxy_url)
        connection = http.client.HTTPSConnection(proxy.hostname, proxy.port or 80, timeout=timeout)
        # HTTPSConnection wraps TLS for the tunnel destination, verifying its name.
        # API headers are sent only after CONNECT and TLS succeed.
        connection.set_tunnel(parts.hostname, 443)
    else:
        connection = http.client.HTTPSConnection(parts.hostname, timeout=timeout)
    try:
        connection.connect()
        connection_socket = connection.sock
        def remaining() -> float:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError
            if connection_socket is not None:
                connection_socket.settimeout(seconds)
            return seconds
        remaining()
        connection.request("GET", parts.path + ("?" + parts.query if parts.query else ""), headers=dict(headers))
        remaining()
        response = connection.getresponse()
        if response.status != 200:
            return HTTPResponse(response.status, b"", _retry_after(response.getheader("Retry-After")))
        declared_length = response.getheader("Content-Length")
        if declared_length is not None:
            try:
                if int(declared_length) > max_bytes:
                    raise InvalidResponse("Paper provider response exceeds the byte limit")
            except ValueError:
                raise InvalidResponse("Paper provider returned an invalid content length") from None
        chunks: list[bytes] = []
        size = 0
        while True:
            remaining()
            chunk = response.read1(min(65_536, max_bytes + 1 - size))
            if not chunk:
                return HTTPResponse(response.status, b"".join(chunks))
            chunks.append(chunk)
            size += len(chunk)
            if size > max_bytes:
                raise InvalidResponse("Paper provider response exceeds the byte limit")
    finally:
        connection.close()


def _integer(value: object, *, minimum: int, maximum: int, default: Any) -> Any:
    if (isinstance(value, str) and len(value) <= len(str(maximum))
            and value.isascii() and value.isdecimal()):
        value = int(value)
    return value if type(value) is int and minimum <= value <= maximum else default


def _paper(record: object) -> Paper:
    if not isinstance(record, dict):
        raise InvalidResponse("Paper provider returned invalid paper metadata")
    paper_id, title = record.get("paperId"), record.get("title")
    if (not isinstance(paper_id, str) or not paper_id.strip() or len(paper_id) > 256
            or not isinstance(title, str) or not title.strip() or len(title) > 10_000):
        raise InvalidResponse("Paper provider omitted a stable paper ID or title")
    paper_id = paper_id.strip()
    if any(ord(char) < 33 for char in paper_id):
        raise InvalidResponse("Paper provider returned an invalid stable paper ID")
    abstract = record.get("abstract")
    if abstract is None:
        abstract = ""
    if not isinstance(abstract, str) or len(abstract) > 200_000:
        raise InvalidResponse("Paper provider returned an invalid abstract")
    url = record.get("url")
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        valid_url = (parts and parts.scheme in {"https", "http"} and parts.hostname
                     and parts.username is None and parts.password is None
                     and len(url) <= 4096 and not any(ord(char) < 33 for char in url))
    except ValueError:
        valid_url = False
    if not valid_url:
        url = "https://www.semanticscholar.org/paper/" + quote(paper_id, safe="")
    publication_date = record.get("publicationDate")
    if isinstance(publication_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", publication_date):
        try:
            date.fromisoformat(publication_date)
        except ValueError:
            publication_date = None
    else:
        publication_date = None
    return Paper(paper_id=paper_id, title=" ".join(title.split()), abstract=abstract.strip(),
                 year=_integer(record.get("year"), minimum=1, maximum=9999, default=None),
                 url=url, citation_count=_integer(record.get("citationCount"), minimum=0, maximum=10**12, default=0),
                 article=None, evidence_scope="abstract_only", publication_date=publication_date)


class SemanticScholarSource:
    """Bounded Semantic Scholar metadata source; never fetches PDFs or full text.

    transport is a synchronous callable (url, headers, timeout, max_bytes) returning
    HTTPResponse, run off the event loop. request_count counts actual attempts.
    Only exact normalized title matches may resolve papers without an ID.
    """

    def __init__(self, api_key: str | None = None, *, timeout: float = 20.0,
                 max_response_bytes: int = 2_000_000, transport: Transport | None = None,
                 proxy_url: str | None = None) -> None:
        self.timeout = _timeout(timeout)
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 10_000_000:
            raise ConfigurationError("Paper response byte limit must be from 1 to 10000000")
        if api_key is not None and (not isinstance(api_key, str) or any(ord(char) < 32 for char in api_key)):
            raise ConfigurationError("Paper API key must be a valid header value")
        self._api_key = api_key
        self.max_response_bytes = max_response_bytes
        _proxy_url(proxy_url)
        self._transport = transport or (partial(_https_request, proxy_url=proxy_url)
                                        if proxy_url else _https_request)
        self.request_count = 0

    @classmethod
    def from_env(cls, *, env: Mapping[str, str] | None = None, **kwargs: Any) -> "SemanticScholarSource":
        env = os.environ if env is None else env
        key = _setting(env, "SAGE_SEMANTIC_SCHOLAR_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "SEMENTIC_SEARCH_API_KEY")
        return cls(api_key=key, proxy_url=_environment_proxy(env), **kwargs)

    @staticmethod
    def _limit(limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ConfigurationError("Paper result limit must be an integer from 1 to 100")
        return limit

    async def _request(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        url = _GRAPH_ROOT + path + "?" + urlencode(params)
        headers = {"Accept": "application/json", "User-Agent": "SAGE-research-workflow/1"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        self.request_count += 1
        try:
            reply = await asyncio.wait_for(asyncio.to_thread(
                self._transport, url, headers, self.timeout, self.max_response_bytes,
            ), timeout=self.timeout)
        except (ConfigurationError, InvalidResponse):
            raise
        except Exception as error:
            raise _provider_error(error, "Paper provider") from None
        if not isinstance(reply, HTTPResponse) or type(reply.status) is not int:
            raise InvalidResponse("Paper transport returned an invalid response")
        if reply.status != 200:
            if reply.status == 429:
                from .errors import RateLimited
                raise RateLimited("Paper provider rate limited (HTTP 429)", reply.retry_after_seconds)
            if reply.status in _TRANSIENT_STATUSES or 500 <= reply.status <= 599:
                raise TransientProviderError(f"Paper provider temporarily unavailable (HTTP {reply.status})")
            raise ProviderError(f"Paper provider request rejected (HTTP {reply.status})")
        if not isinstance(reply.body, bytes) or len(reply.body) > self.max_response_bytes:
            raise InvalidResponse("Paper provider response exceeds the byte limit or is invalid")
        try:
            payload = json.loads(reply.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise InvalidResponse("Paper provider returned malformed JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise InvalidResponse("Paper provider returned an invalid data envelope")
        return payload

    async def search(self, query: str, *, limit: int, publication_date: str | None = None) -> list[Paper]:
        self._limit(limit)
        if not isinstance(query, str) or not query.strip() or len(query) > 4096:
            raise ConfigurationError("Paper search query must contain 1 to 4096 characters")
        params: dict[str, Any] = {"query": query.strip(), "limit": limit, "fields": _PAPER_FIELDS}
        if publication_date is not None:
            if (not isinstance(publication_date, str) or not publication_date
                    or len(publication_date) > 64 or not re.fullmatch(r"[0-9:-]+", publication_date)):
                raise ConfigurationError("publication_date must be a year/date or date range")
            params["publicationDateOrYear"] = publication_date
        payload = await self._request("/paper/search", params)
        return self._papers(payload["data"], limit=limit)

    @staticmethod
    def _papers(records: list[Any], *, limit: int, nested: str | None = None) -> list[Paper]:
        if len(records) > 1000:
            raise InvalidResponse("Paper provider returned too many records")
        papers, seen = [], set()
        for record in records[:limit]:
            if nested:
                if not isinstance(record, dict) or nested not in record:
                    raise InvalidResponse("Paper provider returned malformed citation metadata")
                record = record[nested]
                if record is None:  # Graph API can omit unavailable/removed linked papers.
                    continue
            paper = _paper(record)
            if paper.paper_id not in seen:
                papers.append(paper)
                seen.add(paper.paper_id)
        return papers

    async def related(self, paper: Paper, *, direction: str, limit: int) -> list[Paper]:
        self._limit(limit)
        directions = {"forward": "citations", "citations": "citations", "backward": "references", "references": "references"}
        if not isinstance(direction, str) or direction not in directions:
            raise ConfigurationError("Paper direction must be forward/citations or backward/references")
        paper_id = paper.paper_id
        if not paper_id:
            if not isinstance(paper.title, str) or not paper.title.strip() or len(paper.title) > 4096:
                raise ConfigurationError("Paper requires a stable ID or bounded title")
            # One match request with nested edges, never a hidden lookup + graph
            # request. This preserves one runtime attempt = one HTTP attempt.
            relation = directions[direction]
            fields = "paperId,title,year," + ",".join(
                f"{relation}.{field}" for field in _PAPER_FIELDS.split(","))
            payload = await self._request("/paper/search/match",
                                          {"query": paper.title, "fields": fields})
            normalized = " ".join(paper.title.split()).casefold()
            exact = [record for record in payload["data"]
                     if isinstance(record, dict) and isinstance(record.get("title"), str)
                     and " ".join(record["title"].split()).casefold() == normalized
                     and (paper.year is None or record.get("year") == paper.year)]
            if len(exact) != 1 or not isinstance(exact[0].get(relation), list):
                raise InvalidResponse("Could not unambiguously resolve the paper title and citation metadata")
            _paper(exact[0])  # Require an actual stable ID; no invented identities.
            return self._papers(exact[0][relation], limit=limit)
        if not isinstance(paper_id, str) or len(paper_id) > 256 or any(ord(char) < 33 for char in paper_id):
            raise ConfigurationError("Paper requires a valid stable ID")
        relation = directions[direction]
        payload = await self._request(f"/paper/{quote(paper_id, safe='')}/{relation}",
                                      {"limit": limit, "fields": _PAPER_FIELDS})
        return self._papers(payload["data"], limit=limit,
                            nested="citingPaper" if relation == "citations" else "citedPaper")


def paper_source_from_env(*, env=None, **kwargs):
    """Explicit source selection; Semantic Scholar remains the default."""
    env = os.environ if env is None else env
    provider = _setting(env, "SAGE_PAPER_PROVIDER", default="semantic_scholar")
    if provider == "semantic_scholar":
        return SemanticScholarSource.from_env(env=env, **kwargs)
    if provider == "arxiv":
        from .arxiv import ArxivSource
        return ArxivSource.from_env(env=env, **kwargs)
    if provider == 'arxiv_graph':
        from .graph_source import ArxivGraphSource
        return ArxivGraphSource.from_env(env=env, **kwargs)
    raise ConfigurationError("SAGE_PAPER_PROVIDER must be semantic_scholar, arxiv or arxiv_graph")
