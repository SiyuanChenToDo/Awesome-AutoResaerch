"""Manager-owned retrieval, evidence extraction and scientific critique.

ARIS drives the workflow in DSH; these tools supply the existing SAGE readers
and CoI-derived capsule extractor instead of precomputed paper summaries.
"""
from __future__ import annotations
import asyncio
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socketserver
import stat
import threading
import tempfile
import time
import uuid
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..arxiv import ArxivSource
from ..artifacts import atomic_json
from ..config import RunConfig
from ..providers import OpenAIModel
from ..runtime import Runtime
from ..types import Paper
from ..literature.spans import extract_span_capsule
from ..literature.entailment import capsule_view
from .review import (AXES, RUBRIC_VERSION, canonical_json, input_digest, review_prompt, rubric_descriptor,
                     scientific_input, source_scope, validate_review)
from .novelty import FEEDBACK_VERSION, feedback_prompt, validate_feedback
from .repair import ReviewStageError, validated_completion
from .protocol import protocol_descriptor, protocol_errors
from .report import render_report, validate_report
from .revision_policy import revision_policy, score_observations
from .revision_contract import revision_descriptor, revision_errors


def now():
    return datetime.now(timezone.utc).isoformat()


# Wire payloads larger than this many bytes are archived verbatim to the
# agent-readable shared directory and replaced on the tool transport by a
# small pointer JSON. Measured native-run receipts put search/read at p50
# 22KB and max 80KB, so 128KB keeps ordinary retrievals inline while known
# large payloads (critique receipts ~235KB, team status snapshots >=1.6MB,
# full evidence dumps ~4MB) move out of the DSH session transport.
TOOL_OUTPUT_ARCHIVE_BYTES = 131_072

# Full sections a team status inlines only on explicit request; the compact
# default stays small slot-neutral state plus fixed-size digests.
_TEAM_STATUS_SECTIONS = ('own_proposal', 'frozen_proposals', 'review_history',
                         'incoming_issues', 'revision_history', 'syntheses',
                         'peer_advice_audits')
# Slot-specific snapshot pieces must never enter the shared all-agent file;
# the on-disk reveal barrier matches the former on-the-wire barrier.
_TEAM_SNAPSHOT_SLOT_FIELDS = ('slot', 'role', 'next_action', 'review_target',
                              'target_primary_sha256', 'waiting_for',
                              'own_proposal', 'incoming_issues', 'peer_advice_audits',
                              'session_rotation')


def summarize_tool_output(value):
    """Deterministic shape/scale digest of an archived payload; never calls a model."""
    def describe(item):
        if isinstance(item, dict):
            keys = list(item.keys())
            described = {key: describe(item[key]) for key in keys[:20]}
            summary = {'type': 'object', 'key_count': len(keys), 'keys': described}
            if len(keys) > 20:
                summary['omitted_keys'] = len(keys) - 20
            return summary
        if isinstance(item, list):
            summary = {'type': 'list', 'length': len(item)}
            if item:
                summary['sample_items'] = [describe(element) for element in item[:3]]
            return summary
        if isinstance(item, str):
            return {'type': 'string', 'length': len(item)}
        if isinstance(item, bool):
            return {'type': 'bool'}
        if isinstance(item, (int, float)):
            return {'type': 'number'}
        if item is None:
            return {'type': 'null'}
        return {'type': type(item).__name__}
    return describe(value)


def write_shared_bytes(path, data):
    """Atomically publish manager-written bytes for the native agent OS user.

    The shared tree lives outside the mode-0700 manager-private directory, so
    archive copies use a deterministic 0644 mode and 0755 directories. A
    unique pending name plus os.replace keeps concurrent status threads from
    exposing a partially written file to an agent reader.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o755)
    temporary = path.with_name(path.name + '.pending-' + uuid.uuid4().hex)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(temporary, flags, 0o644)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o644)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def json_object(text):
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def read_confined(path, allowed_root):
    path = Path(path)
    allowed = Path(allowed_root).absolute()
    if os.name == 'posix' and allowed.resolve() != allowed:
        raise ValueError('Artifact root must not traverse a symlink')
    allowed = allowed.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(allowed) or path.is_symlink():
        raise ValueError('Primary artifact must be inside this run')
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
                raise ValueError('Primary artifact missing or too large')
            # On the native Linux host verify the opened object, not an earlier
            # path lookup that an agent could replace before the root read.
            fd_path = Path('/proc/self/fd') / str(stream.fileno())
            if os.name == 'posix' and fd_path.exists() and not fd_path.resolve().is_relative_to(allowed):
                raise ValueError('Opened primary artifact escaped its worktree')
            if (os.name == 'posix' and allowed.resolve() != allowed) or not path.resolve().is_relative_to(allowed):
                raise ValueError('Primary artifact root changed while opening')
            data = stream.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError('Primary artifact too large')
        raw = data.decode('utf-8')
    except OSError:
        raise ValueError('Cannot read the confined primary artifact') from None
    return raw


def read_primary(path, allowed_root):
    raw = read_confined(path, allowed_root)
    return raw, json_object(raw)


def write_confined_report(path, allowed_root, data):
    """Replace only CONJECTURES.md within an opened, confined artifact directory.

    The native Linux manager must never follow an agent-swapped destination
    symlink while writing a file as its own OS user.
    """
    path, root = Path(path), Path(allowed_root).absolute()
    if len(data) > 2_000_000:
        raise ValueError('Report exceeds the 2 MB submission transport limit; preserve the full draft separately')
    parent = path.parent.resolve()
    if path.name != 'CONJECTURES.md' or not parent.is_relative_to(root.resolve()):
        raise ValueError('Report destination escaped the researcher worktree')
    if os.name != 'posix':
        from ..artifacts import atomic_bytes
        atomic_bytes(parent / path.name, data)
        return
    if root.resolve() != root:
        raise ValueError('Artifact root must not traverse a symlink')
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.sage-report-' + uuid.uuid4().hex
    try:
        opened = Path('/proc/self/fd') / str(descriptor)
        if not opened.resolve().is_relative_to(root) or root.resolve() != root:
            raise ValueError('Opened report directory escaped the researcher worktree')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o644, dir_fd=descriptor)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        if not opened.resolve().is_relative_to(root):
            raise ValueError('Report directory moved outside its worktree during rendering')
    finally:
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        os.close(descriptor)


def candidate_errors(document, papers, cards, minimum=8):
    """Evidence and testability checks, explicitly not a novelty/quality proof."""
    errors = []
    candidates = document.get('candidates', [])
    if not isinstance(candidates, list) or len(candidates) < minimum:
        return [f'Generate at least {minimum} distinct candidates before selection']
    seen = set()
    for item in candidates:
        if not isinstance(item, dict):
            errors.append('Candidate must be an object'); continue
        ident = item.get('id', '')
        if not isinstance(ident, str) or not ident.strip() or ident in seen:
            errors.append('Candidate IDs must be nonempty and unique')
        else:
            seen.add(ident)
        for key in ('title', 'problem', 'hypothesis', 'mechanism', 'assumptions'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errors.append(f'{ident}: missing {key}')
        sources = item.get('source_ids', [])
        if (not isinstance(sources, list) or any(not isinstance(x, str) for x in sources) or
                len(set(sources)) < 2 or any(x not in papers for x in sources)):
            errors.append(f'{ident}: needs at least two actually retrieved source IDs')
        elif not any(x in cards and cards[x].get('claims') for x in sources):
            errors.append(f'{ident}: no quote-checked reading supporting its source comparison')
        prior = item.get('closest_prior_art', [])
        if not isinstance(prior, list) or not prior:
            errors.append(f'{ident}: no closest-prior-art comparison')
        else:
            for entry in prior:
                if (not isinstance(entry, dict) or not isinstance(entry.get('paper_id'), str) or
                        entry['paper_id'] not in papers or not entry.get('overlap') or not entry.get('difference')):
                    errors.append(f'{ident}: invalid prior-art comparison')
        plan = item.get('falsification', {})
        if not isinstance(plan, dict) or any(not plan.get(k) for k in ('test', 'controls', 'metric', 'reject_if')):
            errors.append(f'{ident}: specify test, controls, metric and a rejection criterion')
        if not item.get('risks'):
            errors.append(f'{ident}: missing scientific risks')
        if item.get('status') != 'provisional':
            errors.append(f'{ident}: conjectures must remain provisional before experiments and independent review')
    selected = document.get('selected_ids', [])
    if (not isinstance(selected, list) or not selected or
            any(not isinstance(x, str) or x not in seen for x in selected) or
            len(selected) != len(set(selected))):
        errors.append('Select one or more surviving candidate IDs')
    elif any(isinstance(item, dict) and item.get('id') in selected and item.get('disposition') == 'rejected' for item in candidates):
        errors.append('Rejected candidates must remain in the ledger but cannot be selected survivors')
    return errors


class ResearchService:
    def __init__(self, private, run_root, topic, *, max_tools=160, researchers=1, discussion_rounds=2,
                 review_repair_attempts=1, require_protocol=False, enable_peer_audit=False,
                 max_formal_attempts=4, deadline=None):
        self.private, self.run_root, self.topic = Path(private), Path(run_root), topic
        if any((self.private / name).exists() for name in ('evidence.json', 'team-state.json', 'events.jsonl')):
            raise ValueError('Existing research state requires a new run directory; manager recovery is not implemented')
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.papers, self.cards, self.searches, self.reviews, self.grades = {}, {}, [], [], []
        self.archives, self.read_passages = {}, {}
        self.tool_calls, self.max_tools = 0, max_tools
        self.lock = threading.RLock()
        self.idle = threading.Condition(self.lock)
        self.inflight = 0
        self.active_async = {}
        self.stopping = False
        self.shutdown_reason = None
        self.trace_context = threading.local()
        self.event_sequence = 0
        self.team_lock = threading.RLock()
        self.read_locks = {}
        self.search_cooldown = {}
        self.coordination_calls = 0
        self._team_snapshot_sha = None
        if type(review_repair_attempts) is not int or not 0 <= review_repair_attempts <= 2:
            raise ValueError('Use zero to two stage-local review schema repairs')
        self.review_repair_attempts = review_repair_attempts
        self.review_model_calls = 0
        # Explicit compatibility for older embedded callers. The native runner
        # enables the new protocol gate; legacy artifacts remain unverified.
        self.require_protocol = require_protocol
        self.enable_peer_audit = enable_peer_audit
        self.peer_audits, self.peer_audit_locks = {}, {}
        if type(max_formal_attempts) is not int or max_formal_attempts < 1:
            raise ValueError('Formal attempt budget must be a positive integer')
        self.max_formal_attempts, self.formal_attempts = max_formal_attempts, 0
        self.deadline = deadline
        from .team import TeamBoard
        self.team = TeamBoard(self.private, slots=researchers, rounds=discussion_rounds) if researchers > 1 else None
        self.save()

    def save(self):
        with self.lock:
            atomic_json(self.private / 'evidence.json', {'papers': self.papers, 'cards': self.cards,
                'searches': self.searches, 'reviews': self.reviews, 'grades': self.grades,
                'source_archives': self.archives, 'read_passages': self.read_passages, 'tool_calls': self.tool_calls,
                'coordination_calls': self.coordination_calls,
                'review_model_calls': self.review_model_calls,
                'peer_advice_audits': self.peer_audits,
                'formal_attempts_used': self.formal_attempts, 'max_formal_attempts': self.max_formal_attempts,
                'max_tools': self.max_tools, 'deadline_unix': self.deadline,
                'shutdown_reason': self.shutdown_reason,
                'protocol_gate': 'required' if self.require_protocol else 'legacy_unverified',
                'scientific_validation': 'not_performed'})

    def check_admission(self):
        """One admission policy for all public and manager tool dispatches."""
        with self.lock:
            if self.stopping:
                raise ValueError('Research service is stopping; preserve the incomplete run')
            if self.deadline is not None and time.time() >= self.deadline:
                raise ValueError('Run wall-clock budget exhausted before tool dispatch')

    def begin_shutdown(self, reason):
        with self.lock:
            if self.stopping:
                return  # Repeated cancellation must not interrupt client cleanup.
            self.stopping = True
            self.shutdown_reason = reason
            self.event('service_stopping', reason=reason, inflight=self.inflight)
            active = list(self.active_async.values())
        for loop, task in active:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # Already closed by its owning request thread.

    def wait_for_idle(self, timeout):
        with self.idle:
            return self.idle.wait_for(lambda: self.inflight == 0, timeout=max(0, timeout))

    def run_async(self, operation):
        """Cancel a registered request and wait for its executor/client cleanup."""
        async def tracked():
            key = uuid.uuid4().hex
            with self.lock:
                try:
                    self.check_admission()
                except Exception:
                    operation.close()
                    raise
                self.active_async[key] = (asyncio.get_running_loop(), asyncio.current_task())
            try:
                return await self.bounded(operation)
            finally:
                with self.lock:
                    self.active_async.pop(key, None)
        try:
            return asyncio.run(tracked())
        except asyncio.CancelledError:
            raise ValueError('Research request cancelled during service shutdown; no success produced') from None

    def event(self, kind, **fields):
        with self.lock:
            if kind == 'review_model_dispatched':
                self.check_admission()
                if self.deadline is not None and time.time() >= self.deadline:
                    raise ValueError('Run wall-clock budget exhausted before model dispatch')
                # Extra schema attempts spend the same finite research budget.
                if fields['attempt'] > 1 or fields.get('stage') == 'peer_advice_audit':
                    if self.tool_calls >= self.max_tools:
                        raise ValueError('Research tool budget exhausted before review repair')
                    self.tool_calls += 1
                self.review_model_calls += 1
            with (self.private / 'events.jsonl').open('a', encoding='utf-8') as stream:
                self.event_sequence += 1
                stream.write(json.dumps({**fields, 'time': now(), 'event_sequence': self.event_sequence,
                    'kind': kind, 'request_id': getattr(self.trace_context, 'request_id', None)},
                    ensure_ascii=False) + '\n')

    async def close_model(self, model):
        try:
            await asyncio.wait_for(model.aclose(), timeout=5)
        except Exception as exc:
            # A connection-pool shutdown failure cannot erase a completed
            # receipt, mask a validation error or leave a team barrier pending.
            self.event('model_close_failed', error=type(exc).__name__)

    async def bounded(self, operation):
        if self.deadline is None:
            return await operation
        remaining = self.deadline - time.time()
        if remaining <= 0:
            operation.close()
            raise ValueError('Run wall-clock budget exhausted')
        return await asyncio.wait_for(operation, timeout=remaining)

    async def search(self, query, purpose='landscape', limit=8):
        import math
        from urllib.error import HTTPError
        from ..errors import RateLimited, SageError
        from ..literature.reader import arxiv_identity

        if not isinstance(query, str) or not 1 <= len(query) <= 500:
            raise ValueError('Search query must be nonempty and at most 500 characters')
        limit = max(1, min(int(limit), 15))
        record = {'query': query, 'purpose': purpose, 'query_started_at': now(),
                  'arxiv_query': ArxivSource.query_details(query), 'results': [], 'failures': [],
                  'query_policy': ArxivSource.query_instructions,
                  'reading_limits': {}, 'provider_metadata': {}}

        def failure(provider, exc):
            # Never expose arbitrary exception text, URLs or response headers.
            detail = {'provider': provider, 'error': type(exc).__name__,
                      'error_code': exc.code if isinstance(exc, SageError) else 'provider_error',
                      'network_request': getattr(exc, 'network_request', True) is not False}
            status = exc.code if isinstance(exc, HTTPError) else getattr(exc, 'http_status', None)
            if isinstance(exc, RateLimited):
                status = 429
                delay = exc.retry_after_seconds
                detail.update(retry_after_seconds=delay if type(delay) in (int, float)
                              and math.isfinite(delay) and delay >= 0 else None,
                              fresh_retrieval_paused=True)
            if type(status) is int and 100 <= status <= 599:
                detail['http_status'] = status
            record['failures'].append(detail)

        # Search is real on every call, including novelty and counterevidence.
        # During a shared arXiv cooldown, only the explicit fallback may dispatch.
        # No hidden retry/query relaxation: suggestions require another budgeted call.
        try:
            found = await ArxivSource(timeout=35, cooldown=self.search_cooldown,
                                      before_request=self.check_admission).search(query, limit=limit)
            record['results'].extend(asdict(x) for x in found)
        except Exception as exc:
            failure('arxiv', exc)
        if len(record['results']) < 3:
            self.check_admission()
            try:
                url = 'https://api.crossref.org/works?' + urlencode({'query.bibliographic': query, 'rows': limit})
                def fetch():
                    self.check_admission()
                    with urlopen(Request(url, headers={'User-Agent': 'SAGE-autonomous-research/1.0'}), timeout=35) as response:
                        return json.loads(response.read(4_000_001))['message']['items']
                items = await asyncio.to_thread(fetch)
                for item in items:
                    doi = item.get('DOI', '')
                    if not doi or not item.get('title'):
                        continue
                    abstract = re.sub('<[^>]+>', ' ', item.get('abstract', ''))
                    date = item.get('published', {}).get('date-parts', [[]])[0]
                    record['results'].append(asdict(Paper('doi:' + doi, item['title'][0], abstract,
                        year=date[0] if date else None, url='https://doi.org/' + doi,
                        citation_count=None,
                        source_provider='crossref', evidence_scope='abstract_only' if abstract else 'metadata_only')))
                    record['provider_metadata']['doi:' + doi] = {'work_type': item.get('type')}
            except Exception as exc:
                failure('crossref', exc)
        unique = {x['paper_id']: x for x in record['results']}
        record['results'] = list(unique.values())
        for item in record['results']:
            text_available = bool(item.get('article') or item.get('abstract', '').strip())
            official_identity = arxiv_identity(Paper(**item)) is not None
            record['reading_limits'][item['paper_id']] = {
                'readable_text_available': text_available,
                'official_arxiv_text_lookup_supported': official_identity,
                'scope': item['evidence_scope'],
                'limitation': ('No abstract and no supported official arXiv identity; read would return '
                               'NoEvidence. Resolve a relevant official source or retain as unread metadata.'
                               if not text_available and not official_identity else
                               'Only the recorded text scope is available; official full text is not guaranteed.')}
        record['retrieval_status'] = ('degraded' if record['failures'] else
                                      'empty' if not record['results'] else 'retrieved')
        record['comparison_status'] = 'relevance_not_assessed'
        record['next_action'] = ('Use exact paper_id values returned here. Check relevance and reading_limits; '
            'nonempty metadata is not a verified novelty comparison. Suggested shorter queries were not executed '
            'and require a new budgeted search. Do not retry arXiv before its recorded cooldown expires; '
            'unknown Retry-After pauses arXiv retrieval for this run.')
        with self.lock:
            for item in record['results']:
                self.papers[item['paper_id']] = item
            self.searches.append(record)
            self.event('search', **record)
            self.save()
        return record

    async def read(self, paper_id, topic):
        if paper_id not in self.papers:
            raise ValueError('Read requires an ID returned by search')
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError('Read topic must explain the requested research focus')
        if paper_id in self.cards:
            return self.read_view(self.cards[paper_id], topic, cache_hit=True)
        # Validate configuration and the stored paper before allocating a model
        # client. The shared base card always uses the run's research question;
        # a first reader's narrower focus must not silently become everyone's.
        config = RunConfig(evidence_mode='capsule', paper_text_mode='arxiv', capsule_max_chunks=12,
            capsule_max_claims=40, capsule_max_chars=240000, max_tokens_per_call=8192,
            max_reserved_output_tokens=500000, max_wall_seconds=1800,
            request_timeout_seconds=180)
        paper = Paper(**self.papers[paper_id])
        from ..literature.reader import arxiv_identity
        from ..errors import NoEvidence
        if not paper.abstract.strip() and not arxiv_identity(paper):
            raise NoEvidence('No readable abstract or supported official arXiv text is available')
        model = OpenAIModel.from_env(timeout=180)
        runtime = None
        try:
            from ..checkpoints import Checkpoint, identity
            directory = self.private / 'reading-checkpoints'
            directory.mkdir(exist_ok=True, mode=0o700)
            source = ArxivSource()
            checkpoint = Checkpoint(directory / (uuid.uuid4().hex + '.json'),
                identity(self.topic, 'native_paper_read', config, [asdict(paper)], model, model, source))
            self.event('read_checkpoint_created', paper_id=paper_id,
                file=str(checkpoint.path.relative_to(self.private)), scope='manager_private_ordinary_content_only')
            def read_event(rt, event):
                self.event('capsule_runtime', paper_id=paper_id, event=event)
                if event.get('status') == 'request_metadata':
                    self.check_admission()  # Recheck immediately before each nested model request.
            runtime = Runtime(model, model, source, config, checkpoint=checkpoint,
                retain_rejected_responses=True,
                event_sink=read_event)
            evidence = await self.bounded(extract_span_capsule(runtime, paper, self.topic,
                archive_sink=self.archive_source, semantic_audit=True))
            with self.lock:
                self.cards[paper_id] = evidence.capsule
                self.event('read', paper_id=paper_id, capsule=evidence.capsule, usage=runtime.usage, audit=runtime.audit)
                self.save()
            return self.read_view(evidence.capsule, topic, cache_hit=False)
        finally:
            try:
                self.event('read_finished', paper_id=paper_id, usage=runtime.usage if runtime else None)
            finally:
                await self.close_model(model)

    def read_view(self, card, requested_topic, *, cache_hit):
        """Return the shared card without hiding a different requested focus."""
        view = capsule_view(card)
        extraction_topic = card.get('extraction_topic')
        same_focus = requested_topic == extraction_topic if isinstance(extraction_topic, str) else None
        receipt = {'requested_topic': requested_topic, 'extraction_topic': extraction_topic,
            'run_topic': self.topic, 'cache_hit': cache_hit,
            'cache_policy': 'one_shared_card_per_paper_extracted_for_run_topic',
            'requested_topic_matches_extraction': same_focus,
            'focus_status': ('shared_topic_card' if same_focus else
                             'requested_focus_not_separately_extracted' if same_focus is False else
                             'legacy_extraction_topic_unknown'),
            'next_action': ('Use passages(paper_id) for the section outline, then passages(paper_id, chunk_ids) '
                            'to check the original text for your requested focus. This shared card does not '
                            'claim to answer a different focus; no extra extraction was performed.')}
        view['read_request'] = receipt
        self.event('read_returned', paper_id=card.get('paper_id'), **receipt)
        return view

    def archive_source(self, archive):
        paper_id = archive['paper']['paper_id']
        directory = self.private / 'papers'
        directory.mkdir(exist_ok=True, mode=0o700)
        name = hashlib.sha256(paper_id.encode()).hexdigest() + '.json'
        atomic_json(directory / name, archive)
        with self.lock:
            self.archives[paper_id] = {'file': name, 'source_sha256': archive['source_sha256'],
                                      'source_scope': archive['source_scope']}
            self.event('source_archived', paper_id=paper_id, **self.archives[paper_id])
            self.save()

    def passages(self, paper_id, chunk_ids=None):
        if paper_id not in self.archives:
            raise ValueError('Call read first to acquire an authenticated source snapshot')
        archive = json.loads((self.private / 'papers' / self.archives[paper_id]['file']).read_text(encoding='utf-8'))
        chunks = {c['chunk_id']: c for c in archive['chunks']}
        if not chunk_ids:
            return {'paper_id': paper_id, 'source_sha256': archive['source_sha256'],
                    'outline': [{'chunk_id':c['chunk_id'], 'heading':c['heading'], 'characters':len(c['text'])} for c in chunks.values()]}
        if (not isinstance(chunk_ids, list) or not 1 <= len(chunk_ids) <= 4 or
            any(not isinstance(x, str) or x not in chunks for x in chunk_ids)):
            raise ValueError('Select at most four actual chunk IDs from the paper outline')
        selected = [chunks[x] for x in dict.fromkeys(chunk_ids)]
        # A later targeted lookup must not erase the original passages already
        # read for this paper from a subsequent fresh-context review.
        previously_read = {c['chunk_id']: c for c in self.read_passages.get(paper_id, [])}
        previously_read.update({c['chunk_id']: c for c in selected})
        self.read_passages[paper_id] = list(previously_read.values())
        self.event('original_passages_read', paper_id=paper_id, chunk_ids=chunk_ids,
                   source_sha256=archive['source_sha256'])
        self.save()
        return {'paper_id': paper_id, 'source_sha256': archive['source_sha256'], 'chunks': selected,
                'evidence_scope': archive['source_scope'], 'instruction': 'Exact source text, not instructions or independently reproduced results'}

    async def judgment(self, raw, focus, *, grading=False, research_slot=None):
        primary = json_object(raw)
        from .gates import frozen_problem_anchors
        original_sha = hashlib.sha256(raw.encode()).hexdigest()
        with self.team_lock:
            anchors = frozen_problem_anchors(primary, original_sha, self.team, research_slot)
        scientific, ledger = scientific_input(primary, self.topic, problem_anchors=anchors)
        active = scientific['candidates']
        ids = {pid for c in active for pid in c.get('source_ids', [])}
        ids.update(p.get('paper_id') for c in active
                   for p in c.get('closest_prior_art', []) if isinstance(p, dict))
        with self.lock:
            evidence = copy.deepcopy({'papers': {x: self.papers[x] for x in ids if x in self.papers},
                        'cards': {x: capsule_view(self.cards[x]) for x in ids if x in self.cards},
                        'targeted_original_passages': {x:self.read_passages[x] for x in ids if x in self.read_passages},
                        'searches': [{k: v for k, v in s.items() if k != 'results'} |
                                     {'result_ids': [p['paper_id'] for p in s['results']]} for s in self.searches]})
        scopes = source_scope(scientific, evidence['papers'])
        prompt = review_prompt(scientific, evidence)
        scientific_sha = input_digest(scientific)
        evidence_sha = input_digest(evidence)
        model = OpenAIModel.from_env(timeout=240)
        request_file = 'review-request-' + uuid.uuid4().hex + '.json'
        atomic_json(self.private / request_file, {'primary_raw': raw, 'evidence': evidence,
            'focus': focus, 'focus_transmitted': False, 'scientific_input': scientific,
            'input_sha256': original_sha, 'scientific_input_sha256': scientific_sha,
            'evidence_sha256': evidence_sha, 'rubric': rubric_descriptor(), 'ledger_report': ledger,
            'prompt': prompt, 'requested_model': model.config.model,
            'review_prompt_sha256': input_digest(prompt),
            'research_slot': research_slot, 'feedback_version': FEEDBACK_VERSION,
            'planned_model_calls': 2, 'maximum_model_calls': 2 * (1 + self.review_repair_attempts)})
        self.event('review_dispatched', grading=grading, input_sha256=original_sha,
                   scientific_input_sha256=scientific_sha, evidence_sha256=evidence_sha,
                   rubric_version=RUBRIC_VERSION,
                   request_file=request_file)
        stage = 'scientific_review'
        result = None
        model_calls = []
        try:
            # Seven axis rationales and low-rating repairs for every selected
            # candidate need more room than the former holistic scalar review.
            result, calls = await self.bounded(validated_completion(model, stage, prompt,
                lambda value: validate_review(value, scientific, scopes),
                repairs=self.review_repair_attempts, event=self.event,
                rating_slots={(candidate['id'], axis) for candidate in scientific['candidates'] for axis in AXES}))
            model_calls.extend(calls)
            review_usage = copy.deepcopy(model.last_usage)
            reviewer_model = model.last_response_model or model.config.model
            atomic_json(self.private / ('review-progress-' + request_file), {
                'input_sha256': original_sha, 'scientific_input_sha256': scientific_sha,
                'evidence_sha256': evidence_sha, 'partial_review': result,
                'complete_review': False, 'formal_grade': False, 'model_calls': model_calls})
            # A separate stateless call challenges the criticism and its remedy,
            # and builds claim-level novelty feedback. It receives no numeric
            # ratings or past verdicts. It cannot change the frozen rubric score.
            stage = 'novelty_feedback'
            novelty_prompt = feedback_prompt(scientific, evidence, result)
            novelty_request_file = 'novelty-request-' + uuid.uuid4().hex + '.json'
            atomic_json(self.private / novelty_request_file, {
                'input_sha256': original_sha, 'scientific_input_sha256': scientific_sha,
                'evidence_sha256': evidence_sha, 'feedback_version': FEEDBACK_VERSION,
                'prompt': novelty_prompt, 'prompt_sha256': input_digest(novelty_prompt),
                'requested_model': model.config.model, 'research_slot': research_slot})
            self.event('novelty_feedback_dispatched', input_sha256=original_sha,
                       feedback_version=FEEDBACK_VERSION, request_file=novelty_request_file)
            feedback, calls = await self.bounded(validated_completion(model, stage, novelty_prompt,
                lambda value: validate_feedback(value, scientific, scopes, evidence, result),
                repairs=self.review_repair_attempts, event=self.event))
            model_calls.extend(calls)
            # The provider configuration is not an attestation of independence.
            actual = model.last_response_model or model.config.model
            receipt = {'time': now(), 'reviewer_model': reviewer_model, 'research_slot': research_slot,
                'executor_model': os.environ.get('SAGE_MAIN_MODEL', 'unknown'),
                'independent_acceptance': False, 'acceptance_status': 'REVIEW_UNAVAILABLE',
                'independence_reason': 'API identity is not independently attested; same-provider review is advisory',
                'input_sha256': original_sha, 'scientific_input_sha256': scientific_sha,
                'evidence_sha256': evidence_sha, 'rubric_version': RUBRIC_VERSION,
                'review_prompt_sha256': input_digest(prompt),
                'calibration': 'none', 'ledger_report': ledger, 'grading': grading,
                'request_file': request_file,
                'review': result, 'usage': review_usage,
                'feedback_version': FEEDBACK_VERSION, 'novelty_feedback': feedback,
                'novelty_request_file': novelty_request_file,
                'model_calls': model_calls, 'revision_policy': revision_policy()}
            with self.lock:
                receipt['id'] = f'review-{len(self.reviews)+1}'
                self.reviews.append(receipt)
                receipt['score_observations'] = score_observations(self.reviews)
                self.event('review_completed', **receipt)
                self.save()
            return receipt
        except Exception as exc:
            failure = exc if isinstance(exc, ReviewStageError) else ReviewStageError(stage,
                str(exc) if isinstance(exc, ValueError) else type(exc).__name__, [])
            # exc.details (including any ID-level validation_detail) flows into
            # the failure file and the HTTP/MCP review_failure payload unchanged.
            failure.details['model_calls'] = model_calls + failure.details['model_calls']
            failure.details['partial_review'] = copy.deepcopy(result)
            atomic_json(self.private / ('review-failure-' + request_file), failure.details)
            self.event('review_failed', stage=stage, error=type(exc).__name__, usage=None,
                       validation_error=str(failure),
                       partial_review=result, model_calls=failure.details['model_calls'],
                       partial_response=getattr(exc, 'partial_response', None))
            if failure is exc:
                raise
            raise failure from exc
        finally:
            await self.close_model(model)

    def submission_checks(self, raw, document, report_path, allowed_root, agent_id):
        """One authoritative, zero-model check used by preflight AND the grader."""
        sha = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        with self.lock:
            papers, cards, searches, reviews = copy.deepcopy((self.papers, self.cards, self.searches, self.reviews))
        errors = candidate_errors(document, papers, cards)
        if self.require_protocol:
            errors.extend(self.selected_protocol_errors(document))
        if self.team:
            with self.team_lock:
                errors.extend(self.team.grade_errors(document, sha))
                coordinator = self.team.state['roster'].get('0', {}).get('agent_id')
                if not coordinator or agent_id != coordinator:
                    errors.append('Only the manager-identified coordinator may submit a team synthesis')
                if (self.require_protocol and self.team.state['syntheses'] and
                        sha != self.team.state['syntheses'][-1]['primary_sha256']):
                    errors.append('Submit only the latest registered synthesis; restoring an old method requires a new evidence-led revision record')
        report_bytes, report_audit = None, None
        version = self.synthesis_version(sha)
        try:
            report_bytes = read_confined(report_path, allowed_root).encode('utf-8')
            report_audit = validate_report(raw, report_bytes, synthesis_version=version)
            errors.extend(report_audit['errors'])
        except (ValueError, UnicodeError):
            errors.append('Write a current, bound UTF-8 CONJECTURES.md using the report tool before submitting')
        purposes = {s['purpose'] for s in searches if s['results']}
        if len(papers) < 12:
            errors.append('Retrieve at least twelve actual papers from more than one query')
        if len(cards) < 6:
            errors.append('Read at least six papers with quote-checked capsules')
        if not {'novelty', 'counterevidence'} <= purposes:
            errors.append('Perform nonempty novelty and counterevidence searches; rewrite failed/empty queries')
        if not reviews:
            errors.append('Obtain a fresh-context critique and revise before grading')
        if not errors:
            from .gates import advisory_errors
            errors.extend(advisory_errors(sha, reviews, self.team))
        return errors, report_bytes, report_audit, version

    def preflight(self, artifact_path, *, slot=None):
        root = self.run_root / 'native-run' / 'agents'
        agent_id = None
        if self.team:
            with self.team_lock:
                self.team.status(slot)
                identity = self.team.state['roster'][str(slot)]
                root, agent_id = identity['cwd'], identity['agent_id']
        raw, document = read_primary(artifact_path, root)
        errors, _, report_audit, version = self.submission_checks(
            raw, document, Path(artifact_path).parent / 'CONJECTURES.md', root, agent_id)
        scientific, ledger = scientific_input(document, self.topic)
        with self.lock:
            remaining = max(0, self.max_formal_attempts - self.formal_attempts)
        if not remaining:
            errors.append('Formal attempt budget exhausted; do not submit again')
        return {'ready_for_formal_grade': not errors, 'contract_errors': errors,
                'primary_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                'synthesis_version': version, 'report_audit': report_audit,
                'scientific_input': scientific, 'projection_audit': ledger,
                'formal_attempts_remaining': remaining, 'model_calls': 0,
                'scientific_validation': 'not_performed',
                'instruction': 'Resolve these checks, then rerun preflight after EVERY file change. '
                               'This receipt does not reserve a grade or bypass grading checks.'}

    async def grade(self, path, agent_id=None):
        checkout_root = self.run_root / 'native-run' / '.coral' / 'private' / 'grader_checkouts'
        raw = read_confined(path, checkout_root)
        sha = hashlib.sha256(raw.encode()).hexdigest()
        commit = Path(path).parent.name
        with self.lock:
            if self.formal_attempts >= self.max_formal_attempts:
                self.event('formal_attempt_budget_exhausted', input_sha256=sha)
                return {'score': 0.0, 'scientific_score': None, 'evaluation_status': 'budget_exhausted',
                        'score_semantics': 'operational_failure_sentinel_not_scientific_rating',
                        'contract_errors': [], 'evaluation_errors': ['Formal attempt budget exhausted; do not retry'],
                        'scientific_validation': 'not_performed'}
            self.formal_attempts += 1
            self.save()
            papers, cards, searches, reviews = copy.deepcopy((self.papers, self.cards, self.searches, self.reviews))
        try:
            document = json_object(raw)
        except ValueError:
            errors = ['Primary conjectures must be a valid JSON object']
            with self.lock:
                self.grades.append({'commit': commit, 'agent_id': agent_id, 'primary_sha256': sha,
                    'time': now(), 'contract_errors': errors, 'score': 0.0, 'scientific_score': None,
                    'evaluation_status': 'contract_failed',
                    'score_semantics': 'operational_failure_sentinel_not_scientific_rating'})
                self.save()
            return {'score': 0.0, 'scientific_score': None, 'evaluation_status': 'contract_failed',
                    'contract_errors': errors, 'score_semantics': 'operational_failure_sentinel_not_scientific_rating',
                    'scientific_validation': 'not_performed'}
        report_path = Path(path).parent / 'CONJECTURES.md'
        errors, report_bytes, report_audit, version = self.submission_checks(
            raw, document, report_path, checkout_root, agent_id)
        record = {'commit': commit, 'agent_id': agent_id, 'primary_sha256': sha, 'time': now(), 'contract_errors': errors,
                  'synthesis_version': version, 'report_audit': report_audit,
                  'candidate_count': len(document['candidates']) if isinstance(document.get('candidates'), list) else 0, 'score': 0.0}
        if errors:
            with self.lock:
                record.update(evaluation_status='contract_failed', scientific_score=None,
                              score_semantics='operational_failure_sentinel_not_scientific_rating')
                self.grades.append(record); self.save()
            return {'score': 0.0, 'scientific_score': None, 'evaluation_status': 'contract_failed',
                    'score_semantics': 'operational_failure_sentinel_not_scientific_rating',
                    'contract_errors': errors, 'scientific_validation': 'not_performed'}
        try:
            receipt = await self.judgment(raw, 'Evaluate selected scientific proposals using the frozen rubric.', grading=True)
        except Exception as exc:
            record.update(score=None, scientific_score=None, evaluation_status='review_unavailable',
                          evaluation_errors=[type(exc).__name__], review_failure=getattr(exc, 'details', None))
            with self.lock:
                self.grades.append(record); self.save()
            return {'score': 0.0, 'scientific_score': None, 'evaluation_status': 'review_unavailable',
                    'score_semantics': 'operational_failure_sentinel_not_scientific_rating',
                    'contract_errors': [], 'evaluation_errors': record['evaluation_errors'],
                    'review_failure': record['review_failure'], 'scientific_validation': 'not_performed'}
        # Preserve the actual private grader checkout before CORAL removes it.
        # The agent cannot forge either this copy or the grade receipt.
        from ..artifacts import atomic_bytes
        atomic_bytes(self.private / f'conjectures-{sha}.json', raw.encode('utf-8'))
        report_sha = hashlib.sha256(report_bytes).hexdigest()
        report_file = f'report-{sha}-{report_sha}.md'
        atomic_bytes(self.private / report_file, report_bytes)
        review_score = (receipt.get('review') or {}).get('score')
        if not isinstance(review_score, (int, float)):
            return {'score': 0.0, 'scientific_score': None, 'evaluation_status': 'review_receipt_malformed',
                    'contract_errors': [], 'receipt': receipt, 'scientific_validation': 'not_performed',
                    'independent_acceptance': False,
                    'score_semantics': 'operational_failure_sentinel_not_scientific_rating'}
        record.update(score=review_score, review_id=receipt['id'],
                      scientific_score=review_score, evaluation_status='completed',
                      report_sha256=report_sha, report_file=report_file)
        with self.lock:
            self.grades.append(record); self.save()
        return {'score': review_score, 'scientific_score': review_score,
                'evaluation_status': 'completed', 'contract_errors': [], 'receipt': receipt,
                'scientific_validation': 'not_performed', 'independent_acceptance': False}

    def selected_protocol_errors(self, document):
        selected = document.get('selected_ids', [])
        return [f'{candidate.get("id")}: {error}' for candidate in document.get('candidates', [])
                if isinstance(candidate, dict) and candidate.get('id') in selected
                for error in protocol_errors(candidate)]

    def synthesis_version(self, sha):
        if self.team:
            with self.team_lock:
                for synthesis in self.team.state['syntheses']:
                    if synthesis.get('primary_sha256') == sha:
                        return synthesis['receipt']['version']
        return None

    def report(self, artifact_path, narrative='', *, slot=None):
        root = self.run_root / 'native-run' / 'agents'
        if self.team:
            with self.team_lock:
                self.team.status(slot)
                root = self.team.state['roster'][str(slot)]['cwd']
        raw, document = read_primary(artifact_path, root)
        sha = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        version = self.synthesis_version(sha)
        if self.team and (slot != 0 or version is None):
            raise ValueError('Only the coordinator can render a registered current synthesis')
        if self.require_protocol:
            errors = self.selected_protocol_errors(document)
            if errors:
                raise ValueError('; '.join(errors))
        text = render_report(raw, narrative=narrative, synthesis_version=version)
        report_path = Path(artifact_path).resolve().parent / 'CONJECTURES.md'
        with self.lock:
            self.check_admission()
            write_confined_report(report_path, root, text.encode('utf-8'))
        audit = validate_report(raw, text, synthesis_version=version)
        self.event('report_rendered', input_sha256=sha, synthesis_version=version,
                   report_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(), audit=audit)
        return {'path': str(report_path), 'primary_sha256': sha, 'synthesis_version': version,
                'audit': audit}

    def team_call(self, slot, arguments):
        if not self.team or slot is None:
            raise ValueError('Team tools require an authenticated native researcher')
        action = arguments.get('action')
        if action == 'status':
            with self.team_lock:
                snapshot = self.team.snapshot(slot)
                with self.lock:
                    snapshot['peer_advice_audits'] = copy.deepcopy([
                        value for value in self.peer_audits.values() if value['target_slot'] == slot])
                    if (snapshot['next_action'] == 'revise' and any(
                            entry['status'] == 'pending' and entry['round'] == snapshot['round']
                            for entry in snapshot['peer_advice_audits'])):
                        snapshot.update(next_action='wait', waiting_for='peer_advice_audit')
            # Build the compact wire view outside the team lock; the shared
            # snapshot write must not block peers proposing or reviewing.
            return self.team_status_view(snapshot, arguments)
        if action == 'rotate_session':
            # Supervisor-triggered, manager-executed phase-barrier session
            # rotation. The lifecycle supervisor runs as the agent OS user and
            # can never touch the manager-private session state; it only
            # consumes the board's pending one-shot marker over the
            # authenticated slot channel, and the rotation bookkeeping (ledger
            # entry, pointer deletion, receipt) happens here, manager-side.
            phase_key = arguments.get('phase')
            if not isinstance(phase_key, str) or not phase_key.strip():
                raise ValueError('Session rotation must name its phase barrier')
            with self.team_lock:
                reason = self.team.take_session_rotation(slot, phase_key)
                roster = self.team.state['roster'][str(slot)]
                from .dsh_runtime import rotate_session
                result = rotate_session(roster['cwd'], roster['agent_id'],
                                        self.run_root / 'session-state', reason=reason)
            self.event('session_rotated', research_slot=slot, reason=reason,
                       archived_session_id=result['archived_session_id'],
                       rotated_session_count=result['rotated_session_count'])
            return {'rotated': True, 'reason': reason,
                    'archived_session_id': result['archived_session_id'],
                    'rotated_session_count': result['rotated_session_count']}
        with self.team_lock:
            self.team.status(slot)
            if action in ('review', 'revise') and type(arguments.get('round')) is not int:
                raise ValueError('Pass the current round from team status')
            if action in ('propose', 'revise', 'synthesize'):
                # A token identifies the author; accepting an arbitrary peer's
                # artifact path would let one researcher impersonate another.
                root = self.team.state['roster'][str(slot)]['cwd']
                raw = read_confined(arguments['artifact_path'], root)
                sha = hashlib.sha256(raw.encode()).hexdigest()
                # A rejected submission is still an exact, attributable input.
                # Retain before parsing so later edits cannot change its meaning.
                from ..artifacts import atomic_bytes
                input_file = f'team-input-{sha}.json'
                if not (self.private / input_file).exists():
                    atomic_bytes(self.private / input_file, raw.encode('utf-8'))
                self.event('team_artifact_read', research_slot=slot, action=action,
                    primary_sha256=sha, file=input_file, bytes=len(raw.encode('utf-8')))
                document = json_object(raw)
                minimum = 8 if action == 'synthesize' else (8 + self.team.slots - 1) // self.team.slots
                errors = candidate_errors(document, self.papers, self.cards, minimum=minimum)
                if self.require_protocol:
                    errors.extend(self.selected_protocol_errors(document))
                if errors:
                    raise ValueError('; '.join(errors))
                if action == 'propose':
                    with self.lock:
                        self.check_admission()
                        return self.team.propose(slot, document, sha)
                if action == 'revise':
                    self.check_team_sources(arguments.get('decisions', []))
                    if self.enable_peer_audit:
                        relevant = [entry for entry in self.peer_audits.values()
                                    if entry['target_slot'] == slot and entry['round'] == arguments['round']]
                        if any(entry['status'] == 'pending' for entry in relevant):
                            raise ValueError('Peer advice audit is pending; wait for its receipt before revision')
                        for decision in arguments['decisions']:
                            for key in ('problem_assessment', 'remedy_assessment', 'remaining_uncertainty', 'audit_response'):
                                if not isinstance(decision.get(key), str) or not decision[key].strip():
                                    raise ValueError('Each peer decision needs ' + key + '; an accepted label is not a verified repair')
                    with self.lock:
                        self.check_admission()
                        return self.team.revise(slot, document, sha, arguments['decisions'],
                                                expected_round=arguments['round'])
                if self.require_protocol and self.team.state['syntheses']:
                    previous = self.team.state['syntheses'][-1]
                    if previous['primary_sha256'] != sha:
                        errors = revision_errors(previous['document'], previous['primary_sha256'], document,
                                                 known_sources=self.papers)
                        if errors:
                            raise ValueError('; '.join(errors))
                with self.lock:
                    self.check_admission()
                    return self.team.synthesize(slot, document, sha)
            if action == 'review':
                self.check_team_sources(arguments.get('issues', []))
                with self.lock:
                    self.check_admission()
                    receipt = self.team.review(slot, arguments['target_slot'], arguments['proposal_sha256'], arguments['issues'],
                                               expected_round=arguments['round'])
                if self.enable_peer_audit:
                    key = str(receipt['sequence'])
                    with self.lock:
                        if key not in self.peer_audits:
                            self.peer_audits[key] = {'status': 'pending', 'review_receipt': receipt,
                                'reviewer_slot': slot, 'target_slot': arguments['target_slot'],
                                'round': arguments['round']}
                            self.peer_audit_locks[key] = threading.Lock()
                            self.save()
                return receipt
            raise ValueError('Use team action status/propose/review/revise/synthesize')

    def team_status_view(self, snapshot, arguments):
        """Compact status by default; archive the all-agent snapshot for local reads.

        Full sections stay available in one call through ``sections=[...]`` or
        ``detail="full"`` so agents can fetch exact full data occasionally
        instead of polling multi-megabyte snapshots over the MCP transport.
        The shared file deliberately excludes slot-specific fields (own
        proposal, incoming issues, peer advice audits, review target): the
        on-disk reveal barrier must match the former on-the-wire barrier.
        """
        detail = arguments.get('detail')
        if detail is not None and detail != 'full':
            raise ValueError('team status detail must be exactly "full"')
        sections = arguments.get('sections')
        if sections is None:
            requested = []
        elif not isinstance(sections, list) or any(not isinstance(name, str) for name in sections):
            raise ValueError('team status sections must be a list of section names')
        else:
            requested = list(sections)
        unknown = sorted({name for name in requested if name not in _TEAM_STATUS_SECTIONS})
        if unknown:
            raise ValueError('Unknown team status sections: ' + ', '.join(unknown) +
                             '; available: ' + ', '.join(_TEAM_STATUS_SECTIONS))
        if detail == 'full':
            requested = list(_TEAM_STATUS_SECTIONS)
        view = {key: snapshot[key] for key in (
            'schema_version', 'slots', 'rounds', 'phase', 'round', 'complete',
            'registered_agents', 'proposal_count', 'review_count', 'revision_count',
            'synthesis_count', 'event_count', 'scientific_validation', 'independent_acceptance',
            'slot', 'role', 'next_action', 'review_target', 'target_primary_sha256',
            'waiting_for', 'session_rotation') if key in snapshot}
        own = snapshot.get('own_proposal')
        view['own_proposal'] = None if own is None else {
            'primary_sha256': own.get('primary_sha256'),
            'candidate_count': len(own.get('document', {}).get('candidates', []))}
        frozen = snapshot.get('frozen_proposals', {})
        view['frozen_slots'] = sorted(frozen, key=int)
        view['frozen_shas'] = {key: frozen[key]['primary_sha256'] for key in view['frozen_slots']}
        view['review_history_rounds'] = [entry['round'] for entry in snapshot.get('review_history', [])]
        view['revision_history_rounds'] = [entry['round'] for entry in snapshot.get('revision_history', [])]
        view['synthesis_shas'] = [entry['primary_sha256'] for entry in snapshot.get('syntheses', [])]
        view['incoming_issue_count'] = len(snapshot.get('incoming_issues', []))
        view['peer_advice_audit_count'] = len(snapshot.get('peer_advice_audits', []))
        view['available_sections'] = list(_TEAM_STATUS_SECTIONS)
        shared = {key: value for key, value in snapshot.items()
                  if key not in _TEAM_SNAPSHOT_SLOT_FIELDS}
        shared_bytes = json.dumps(shared, ensure_ascii=False).encode('utf-8')
        shared_sha = hashlib.sha256(shared_bytes).hexdigest()
        if shared_sha != self._team_snapshot_sha:
            try:
                write_shared_bytes(self.shared_public_root() / 'team-snapshot.json', shared_bytes)
                self._team_snapshot_sha = shared_sha
            except OSError as exc:
                view['snapshot_error'] = type(exc).__name__
        if self._team_snapshot_sha == shared_sha:
            view['snapshot_file'] = '.coral/public/team-snapshot.json'
            view['snapshot_sha256'] = shared_sha
        for name in requested:
            view[name] = snapshot[name]
        return view

    def check_team_sources(self, entries):
        if not isinstance(entries, list):
            raise ValueError('Expected a list of source-bound issues or decisions')
        for entry in entries:
            ids = entry.get('source_ids', []) if isinstance(entry, dict) else None
            if not isinstance(ids, list) or any(not isinstance(x, str) or x not in self.papers for x in ids):
                raise ValueError('Team evidence must name actually retrieved source IDs')

    def audit_peer_receipt(self, receipt):
        """Audit a published frozen review outside the global/team locks."""
        from .peer_audit import audit_peer_advice
        key = str(receipt['sequence'])
        with self.peer_audit_locks[key]:
            with self.lock:
                existing = copy.deepcopy(self.peer_audits[key])
            if existing['status'] != 'pending':
                return existing
            with self.team_lock:
                number, reviewer = receipt['round'], str(receipt['slot'])
                review = copy.deepcopy(self.team.state['rounds'][str(number)]['reviews'][reviewer])
                target = self.team._frozen(number)[str(receipt['target_slot'])]
                document = copy.deepcopy(target['document'])
                if target['primary_sha256'] != receipt['proposal_sha256']:
                    raise ValueError('Peer audit frozen target changed')
            ids = {pid for candidate in document['candidates'] for pid in candidate.get('source_ids', [])}
            ids.update(prior.get('paper_id') for candidate in document['candidates']
                       for prior in candidate.get('closest_prior_art', []) if isinstance(prior, dict))
            ids.update(pid for issue in review['issues'] for pid in issue.get('source_ids', []))
            with self.lock:
                evidence = copy.deepcopy({'papers': {pid: self.papers[pid] for pid in ids if pid in self.papers},
                    'cards': {pid: capsule_view(self.cards[pid]) for pid in ids if pid in self.cards},
                    'targeted_original_passages': {pid: self.read_passages[pid] for pid in ids if pid in self.read_passages}})

            async def perform():
                model = None
                try:
                    if not review['issues']:
                        return {'status': 'not_needed', 'issue_count': 0, 'model_calls': [],
                                'automatic_application': False, 'independent_acceptance': False}
                    model = OpenAIModel.from_env(timeout=240)
                    return await self.bounded(audit_peer_advice(model, document, evidence, review['issues'],
                        repairs=self.review_repair_attempts, event=self.event))
                except Exception as exc:
                    return {'status': 'unavailable', 'error': type(exc).__name__,
                            'complete_audit': False, 'original_peer_review_preserved': True,
                            'automatic_application': False, 'independent_acceptance': False}
                finally:
                    if model:
                        await self.close_model(model)
            result = self.run_async(perform())
            with self.lock:
                existing.update(result)
                self.peer_audits[key] = existing
                self.event('peer_advice_audit_completed', receipt=existing)
                self.save()
            return copy.deepcopy(existing)

    def call(self, tool, arguments, *, slot=None):
        """Correlate one tool transfer with its nested retrieval/review events.

        Canonical digests cover the complete transported JSON; existing frozen
        review requests, source archives and team receipts retain actual data.
        Observation never calls a research tool or spends a research budget.
        """
        previous = getattr(self.trace_context, 'request_id', None)
        request_id = uuid.uuid4().hex
        self.trace_context.request_id = request_id
        started = time.monotonic()
        with self.idle:
            self.inflight += 1
        try:
            try:
                argument_sha = input_digest(arguments)
            except (TypeError, ValueError):
                self.event('tool_transfer_started', tool=tool, research_slot=slot,
                    arguments=None, input_sha256=None, invalid_json_input=True)
                raise ValueError('Tool arguments must be finite JSON values') from None
            self.event('tool_transfer_started', tool=tool, research_slot=slot,
                arguments=arguments, input_sha256=argument_sha)
            result = self._call(tool, arguments, slot=slot)
            body = canonical_json(result).encode('utf-8')
            # Preserve the whole boundary payload, including rejected/uncertain
            # evidence. A digest alone cannot diagnose downstream truncation.
            from ..artifacts import atomic_bytes
            wire_body = json.dumps(result, ensure_ascii=False).encode('utf-8')
            wire_sha = hashlib.sha256(wire_body).hexdigest()
            output_file = f'tool-output-{wire_sha}.json'
            with self.lock:
                if not (self.private / output_file).exists():
                    atomic_bytes(self.private / output_file, wire_body)
            # Repeated multi-megabyte results (team status snapshots, full
            # evidence dumps) must not ride the MCP/DSH transport every call.
            # Archive one agent-readable copy and return a small pointer; the
            # private copy above stays the canonical event artifact.
            archived_file, archive_error = self._archive_tool_output(output_file, wire_body)
            if archived_file is not None:
                archived_result = result
                result = {'archived': True, 'tool': tool, 'full_bytes': len(wire_body),
                    'output_sha256': wire_sha, 'output_file': archived_file,
                    'summary': summarize_tool_output(archived_result)}
            event_result = result if archived_file is None else archived_result
            lineage = {key: event_result[key] for key in (
                'id', 'paper_id', 'input_sha256', 'primary_sha256', 'proposal_sha256',
                'review_id', 'request_file', 'synthesis_version', 'phase', 'status')
                if isinstance(event_result, dict) and key in event_result}
            self.event('tool_transfer_completed', tool=tool, research_slot=slot,
                output_sha256=hashlib.sha256(body).hexdigest(), output_bytes=len(body),
                output_file=output_file, wire_json_sha256=wire_sha, wire_json_bytes=len(wire_body),
                archived_file=archived_file, archive_error=archive_error,
                output_keys=sorted(event_result) if isinstance(event_result, dict) else None,
                lineage=lineage, elapsed_seconds=time.monotonic() - started)
            return result
        except Exception as exc:
            self.event('tool_transfer_failed', tool=tool, research_slot=slot,
                error=type(exc).__name__,
                message=str(exc) if isinstance(exc, ValueError) else 'Provider/tool failed; original receipt retained',
                review_failure=exc.details if isinstance(exc, ReviewStageError) else None,
                elapsed_seconds=time.monotonic() - started)
            raise
        finally:
            self.trace_context.request_id = previous
            with self.idle:
                self.inflight -= 1
                self.idle.notify_all()

    def shared_public_root(self):
        """Agent-readable shared artifact tree derived from the run directory."""
        return self.run_root / 'native-run' / '.coral' / 'public'

    def _archive_tool_output(self, output_file, wire_body):
        """Publish one agent-readable copy of an oversized wire payload.

        Content-addressed name means an existing shared copy is already exact;
        a failed best-effort write falls back to the inline result so the tool
        call itself still succeeds (the manager-private copy is retained).
        """
        if len(wire_body) <= TOOL_OUTPUT_ARCHIVE_BYTES:
            return None, None
        relative = '.coral/public/tool-archive/' + output_file
        try:
            target = self.shared_public_root() / 'tool-archive' / output_file
            if not target.exists():
                write_shared_bytes(target, wire_body)
            return relative, None
        except OSError as exc:
            return None, type(exc).__name__

    def _call(self, tool, arguments, *, slot=None):
        self.check_admission()
        if self.team and tool != 'grade':
            with self.team_lock:
                if slot is None:
                    raise ValueError('Team tools require an authenticated native researcher')
                self.team.status(slot)
        with self.lock:
            self.check_admission()
            if tool == 'team':
                self.coordination_calls += 1
                if self.coordination_calls > 4000:
                    raise ValueError('Coordination budget exhausted; preserve the incomplete team state')
            else:
                self.tool_calls += 1
                if self.tool_calls > self.max_tools:
                    raise ValueError('Research tool budget exhausted; all previous attempts retained')
            self.event('tool_dispatched', tool=tool, research_slot=slot)
            self.save()
        # Do not hold the global state lock across paid/network calls. In
        # particular a slow paper read must not block all team barriers.
        if tool == 'team':
            result = self.team_call(slot, arguments)
            if self.enable_peer_audit and arguments.get('action') == 'review':
                try:
                    audit = self.audit_peer_receipt(result)
                except Exception as exc:
                    # The published peer review survives audit infrastructure
                    # failures. Never leave an irreversible pending barrier.
                    key = str(result['sequence'])
                    with self.lock:
                        self.peer_audits[key].update(status='unavailable', complete_audit=False,
                            error=type(exc).__name__, original_peer_review_preserved=True)
                        audit = copy.deepcopy(self.peer_audits[key])
                        self.event('peer_advice_audit_failed', receipt=audit)
                        self.save()
                result = {**result, 'advice_audit': audit}
            return result
        if tool == 'search':
            return self.run_async(self.search(**arguments))
        if tool == 'read':
            with self.lock:
                read_lock = self.read_locks.setdefault(arguments['paper_id'], threading.Lock())
            while not read_lock.acquire(timeout=0.1):
                self.check_admission()
            try:
                return self.run_async(self.read(**arguments))
            finally:
                read_lock.release()
        if tool == 'passages':
            with self.lock:
                return self.passages(**arguments)
        if tool == 'critique':
            root = self.run_root / 'native-run' / 'agents'
            if self.team:
                with self.team_lock:
                    self.team.status(slot)
                    root = self.team.state['roster'][str(slot)]['cwd']
            raw, _ = read_primary(arguments['artifact_path'], root)
            return self.run_async(self.judgment(raw, arguments['focus'], research_slot=slot))
        if tool == 'grade':
            return self.run_async(self.grade(arguments['artifact_path'], agent_id=arguments.get('agent_id')))
        if tool == 'protocol_schema':
            return {**protocol_descriptor(), 'revision_contract': revision_descriptor()}
        if tool == 'report':
            return self.report(**arguments, slot=slot)
        if tool == 'preflight':
            return self.preflight(**arguments, slot=slot)
        if tool == 'evidence':
            paper_ids = arguments.get('paper_ids')
            include = arguments.get('include')
            if paper_ids is not None and (not isinstance(paper_ids, list)
                                          or any(not isinstance(value, str) for value in paper_ids)):
                raise ValueError('evidence paper_ids must be a list of paper ID strings')
            if include is not None and (not isinstance(include, list)
                                        or any(not isinstance(value, str) for value in include)):
                raise ValueError('evidence include must be a list of section names')
            sections = ['papers', 'cards', 'reviews', 'searches'] if include is None else list(include)
            unknown = sorted({name for name in sections if name not in ('papers', 'cards', 'reviews', 'searches')})
            if unknown:
                raise ValueError('Unknown evidence sections: ' + ', '.join(unknown) +
                                 '; available: papers, cards, reviews, searches')
            hide_peer_reviews = False
            if self.team:
                with self.team_lock:
                    hide_peer_reviews = self.team.summary()['phase'] == 'proposing'
            with self.lock:
                visible_reviews = ([r for r in self.reviews if r.get('research_slot') == slot]
                                   if hide_peer_reviews else self.reviews)
                selected = None if paper_ids is None else list(dict.fromkeys(paper_ids))
                wanted = list(self.papers) if selected is None else selected
                payload = {}
                if 'papers' in sections:
                    payload['papers'] = copy.deepcopy(
                        {key: self.papers[key] for key in wanted if key in self.papers})
                if 'cards' in sections:
                    payload['cards'] = copy.deepcopy(
                        {key: capsule_view(self.cards[key]) for key in wanted if key in self.cards})
                if 'reviews' in sections:
                    payload['reviews'] = copy.deepcopy(visible_reviews)
                if 'searches' in sections:
                    payload['searches'] = copy.deepcopy(self.searches)
                payload['independent_acceptance'] = False
                if selected is not None:
                    payload['paper_ids'] = selected
                    payload['unknown_paper_ids'] = [key for key in selected if key not in self.papers]
                return payload
        raise ValueError('Unknown research tool')


def serve(service, token):
    from .dsh_runtime import team_token
    slot_tokens = {team_token(token, slot): slot for slot in range(service.team.slots)} if service.team else {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.connection.settimeout(15)
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.send_error(400); return
            if not 0 < size <= 2_000_000:
                self.send_error(413); return
            supplied = self.headers.get('Authorization', '').removeprefix('Bearer ')
            master = hmac.compare_digest(supplied, token)
            slot = slot_tokens.get(supplied)
            if not master and slot is None:
                # Consume the bounded request before closing. Leaving it unread
                # can reset the socket on Windows and hide the intended 403.
                self.rfile.read(size)
                self.send_error(403); return
            try:
                req = json.loads(self.rfile.read(size))
                if req.get('tool') == 'grade':
                    raise ValueError('Grading is available only through the manager-private CORAL socket')
                if req.get('tool') == 'runtime_register':
                    if not master or not service.team:
                        raise ValueError('Only the manager runtime can register a native session')
                    args = req['arguments']
                    cwd = Path(args['cwd']).resolve()
                    if not cwd.is_relative_to((service.run_root / 'native-run' / 'agents').resolve()):
                        raise ValueError('Native researcher worktree must belong to this run')
                    from .dsh_runtime import checked_id
                    checked_id(args['session_id'])
                    with service.idle:
                        service.check_admission()
                        service.inflight += 1
                    try:
                        with service.team_lock:
                            service.check_admission()
                            value = service.team.register(**args)
                        service.event('native_researcher_registered', **args)
                    finally:
                        with service.idle:
                            service.inflight -= 1
                            service.idle.notify_all()
                else:
                    if service.team and master:
                        raise ValueError('Team research calls require a per-researcher token')
                    value = service.call(req['tool'], req.get('arguments', {}), slot=slot)
            except Exception as exc:
                service.event('tool_failed', error=type(exc).__name__)
                value = {'error': type(exc).__name__, 'message': str(exc) if isinstance(exc, ValueError) else 'Provider/tool failed; evidence and failed attempt retained'}
                from ..errors import NoEvidence
                if isinstance(exc, NoEvidence):
                    value.update(error_code='no_evidence', message='No usable abstract or supported official paper text was available. Inspect source scope and reading limits, or retrieve another relevant readable source.')
                if isinstance(exc, ReviewStageError):
                    value['review_failure'] = exc.details
            body = json.dumps(value, ensure_ascii=False, default=str).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def serve_grader(service):
    """OS-protected grading channel, inaccessible even with the agent tool token."""
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                request = json.loads(self.rfile.readline(2_000_001))
                value = service.call('grade', {'artifact_path': request['artifact_path'], 'agent_id': request.get('agent_id')})
            except Exception as exc:
                service.event('grade_failed', error=type(exc).__name__)
                value = {'error': type(exc).__name__}
                if isinstance(exc, ReviewStageError):
                    value['review_failure'] = exc.details
            self.wfile.write(json.dumps(value, ensure_ascii=False, default=str).encode() + b'\n')
    # AF_UNIX paths are limited to about 108 bytes on Linux. Research project
    # paths are often longer; use an exclusively created mode-0700 directory.
    directory = Path(tempfile.mkdtemp(prefix='sage-grade-'))
    directory.chmod(0o700)
    path = directory / 'grader.sock'
    server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
    path.chmod(0o600)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, path
