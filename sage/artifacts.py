"""Private, incremental local artifacts. Persistence is not scientific validation."""
import json
import os
from pathlib import Path


def atomic_bytes(path, data):
    """Preserve exact graded bytes across operating-system newline conventions."""
    path = Path(path)
    temporary = path.with_name(path.name + '.pending')
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(temporary, flags, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_text(path, text):
    path = Path(path)
    temporary = path.with_name(path.name + '.pending')
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(temporary, flags, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


class ProgressArtifacts:
    """Flush each audit event and a phase snapshot before the next provider call."""

    def __init__(self, destination):
        self.destination = Path(destination)
        self.runtime = None
        self.state = {'schema_version': 'sage.laboratory.v1', 'status': 'starting',
                      'proposal': None, 'execution': None, 'report': None,
                      'scientific_validation': 'not_performed', 'errors': []}
        self.initialized = False

    def event(self, runtime, event):
        self.runtime = runtime
        path = self.destination / 'audit.jsonl'
        if not self.initialized:
            atomic_text(path, ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in runtime.audit))
            self.initialized = True
        else:
            flags = os.O_WRONLY | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
            with os.fdopen(os.open(path, flags), 'w', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        self.snapshot(self.state)

    def snapshot(self, result):
        self.state = result
        record = dict(result)
        if self.runtime is not None:
            record['usage'] = dict(self.runtime.usage)
            record['audit'] = list(self.runtime.audit)
        atomic_json(self.destination / 'result.partial.json', record)
