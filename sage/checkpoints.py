"""Versioned exact-input checkpoints. Local integrity checks are not signatures.

Never deserialize code. An in-flight remote request is ambiguous after a crash;
refuse to repeat it unless the operator explicitly opts in. Atomic replacement
cannot provide exactly-once execution at a remote provider.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from .errors import ConfigurationError

VERSION = 'sage.checkpoint.v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def code_version():
    root = Path(__file__).parent
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.rglob('*.py'))})


def provider_identity(provider):
    config = getattr(provider, 'config', None)
    # Never serialize credentials, proxy addresses, or arbitrary provider reprs.
    return {'class': type(provider).__module__ + '.' + type(provider).__qualname__,
            'settings': {key: getattr(config, key, None) for key in
                         ('model', 'provider', 'endpoint', 'is_azure', 'api_version',
                          'deepseek_thinking', 'embedding_model', 'embedding_endpoint', 'embedding_api_version')},
            'chain_relation': getattr(provider, 'chain_relation', None)}


def identity(topic, mode, config, articles, main_model, cheap_model, source):
    return {'schema': VERSION, 'code_sha256': code_version(),
            'input_sha256': digest({'topic': topic, 'mode': mode, 'articles': articles,
                                    'config': config.to_dict()}),
            'providers_sha256': digest([provider_identity(x) for x in (main_model, cheap_model, source)])}


def encode(value):
    from .types import Paper
    if isinstance(value, Paper):
        return {'__sage_paper__': asdict(value)}
    if isinstance(value, list):
        return [encode(x) for x in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ConfigurationError('Unsupported checkpoint value')


def decode(value):
    from .types import Paper
    if isinstance(value, dict):
        if set(value) == {'__sage_paper__'}:
            fields = dict(value['__sage_paper__'])
            fields['authors'] = tuple(fields.get('authors', ()))
            return Paper(**fields)
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(x) for x in value]
    return value


class Checkpoint:
    def __init__(self, path, expected_identity, *, resume=None):
        self.path = Path(path).absolute()
        self.identity = expected_identity
        self.entries = {}
        self.rejections = []
        self.audit = []
        self.usage = None
        self.elapsed = 0.0
        for path in (self.path, Path(resume).absolute() if resume else self.path):
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ConfigurationError('Checkpoint paths must not traverse symlinks')
        if self.path.exists():
            raise ConfigurationError('Checkpoint destination already exists')
        if resume:
            try:
                source = Path(resume)
                if source.stat().st_size > 100_000_000:
                    raise ValueError
                envelope = json.loads(source.read_text())
                data = envelope['data']
                if digest(data) != envelope['sha256'] or data['identity'] != expected_identity:
                    raise ValueError
                self.entries, self.audit = data['entries'], data['audit']
                self.rejections = data.get('rejections', [])
                if not isinstance(self.rejections, list):
                    raise ValueError
                self.usage, self.elapsed = data['usage'], data['elapsed_seconds']
                if not isinstance(self.entries, dict) or not isinstance(self.audit, list):
                    raise ValueError
                for kind in ('model', 'search'):
                    if self.usage[kind + '_calls'] != sum(e.get('kind') == kind and e['status'] == 'started' for e in self.audit):
                        raise ValueError
                if not isinstance(self.elapsed, (int, float)) or not 0 <= self.elapsed < 1e9:
                    raise ValueError
            except (OSError, ValueError, TypeError, KeyError):
                raise ConfigurationError('Checkpoint is invalid or belongs to different code, inputs, providers, or limits') from None

    def save(self, runtime):
        data = {'identity': self.identity, 'entries': self.entries, 'rejections': self.rejections, 'audit': runtime.audit,
                'usage': runtime.usage, 'elapsed_seconds': runtime.elapsed_before + runtime.clock() - runtime.started}
        body = json.dumps({'data': data, 'sha256': digest(data)}, ensure_ascii=False, allow_nan=False)
        temporary = self.path.with_suffix('.pending')
        # Output directory is private and checked by CLI. No secret environment is stored.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
