"""Loopback-only research console over existing autonomous run artifacts.

No database, model calls, or scientific writes in the observation path. Starting
a run invokes the same CLI with an explicit finite budget and live opt-in.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit

from .artifacts import atomic_json

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).with_name('console_static')
ARTIFACTS = ('conjectures.json', 'CONJECTURES.md', 'latest-conjectures.json',
             'latest-CONJECTURES.md', 'best-score-conjectures.json',
             'best-score-CONJECTURES.md', 'result.json')


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def process_alive(identity):
    """Never infer liveness from PID existence alone; reused PIDs are not runs."""
    if not isinstance(identity, dict) or type(identity.get('pid')) is not int:
        return None
    if os.name != 'posix' or not Path('/proc').is_dir():
        return None
    try:
        stat = Path(f"/proc/{identity['pid']}/stat").read_text().rsplit(')', 1)[1].split()
        return stat[0] != 'Z' and str(identity.get('start_ticks')) == stat[19]
    except (FileNotFoundError, ProcessLookupError):
        return False
    except (OSError, IndexError):
        return None


class RunStore:
    def __init__(self, projects, *, allow_live=False, repo=ROOT):
        original = Path(projects).absolute()
        if any(p.is_symlink() for p in (original, *original.parents)):
            raise ValueError('Projects directory cannot traverse symlinks')
        self.projects, self.repo = original.resolve(), Path(repo).resolve()
        self.allow_live = allow_live
        self.lock = threading.RLock()
        self.cache = {}
        self.children = {}
        self.control = self.projects / '.console'

    def path(self, ident):
        if (not isinstance(ident, str) or not ident or '\\' in ident or
                any(not part or part.startswith('.') for part in ident.split('/'))):
            raise ValueError('Invalid run ID')
        p = self.projects / ident
        if any(x.is_symlink() for x in (p, *p.parents)):
            raise ValueError('Symlinked run paths are not served')
        resolved = p.resolve()
        if not resolved.is_relative_to(self.projects) or resolved == self.projects:
            raise ValueError('Run path is outside projects')
        return resolved

    def read(self, path):
        """Atomic product snapshots; a partial/missing snapshot is never a pass."""
        if any(p.is_symlink() for p in (path, *path.parents)):
            return {}, 'unsafe_symlink'
        try:
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
            with self.lock:
                cached = self.cache.get(str(path))
                if cached and cached[0] == key:
                    return cached[1], None
            if stat.st_size > 128 * 1024 * 1024:
                return {}, 'snapshot_too_large'
            obj = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(obj, dict):
                return {}, 'snapshot_not_object'
            with self.lock:
                self.cache[str(path)] = (key, obj)
                if len(self.cache) > 64:
                    self.cache.pop(next(iter(self.cache)))
            return obj, None
        except FileNotFoundError:
            return {}, 'not_written'
        except (OSError, ValueError):
            return {}, 'snapshot_unavailable'

    def run_ids(self):
        found = set()
        for pattern in ('*/launch.json', '*/*/launch.json'):
            for file in self.projects.glob(pattern):
                ident = file.parent.relative_to(self.projects).as_posix()
                try:
                    if self.path(ident).is_dir():
                        found.add(ident)
                except ValueError:
                    pass
        if self.control.is_dir():
            for file in self.control.glob('console-*.json'):
                found.add(file.stem)
        def start_key(ident):
            launch, _ = self.read(self.path(ident) / 'launch.json')
            request, _ = self.read(self.control / (ident + '.json')) if '/' not in ident else ({}, None)
            started = launch.get('started') or request.get('started')
            try:
                stamp = datetime.fromisoformat(started.replace('Z', '+00:00'))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                return stamp.timestamp(), ident
            except (AttributeError, TypeError, ValueError, OverflowError):
                return float('-inf'), ident
        return sorted(found, key=start_key, reverse=True)

    def summary(self, ident):
        run = self.path(ident)
        launch, launch_error = self.read(run / 'launch.json')
        result, result_error = self.read(run / 'result.json')
        evidence, evidence_error = self.read(run / 'service-private' / 'evidence.json')
        team, team_error = self.read(run / 'service-private' / 'team-state.json')
        request, _ = self.read(self.control / (ident + '.json')) if '/' not in ident else ({}, None)
        child = self.children.get(ident)
        running = child.poll() is None if child else process_alive(launch.get('launcher_identity'))
        final = bool(result)
        reported_complete = result.get('workflow_status') == 'completed_autonomous_conjectures'
        grades = evidence.get('grades', [])
        selected = result.get('selected_grade', {})
        complete = reported_complete and selected.get('evaluation_status') == 'completed' and any(
            g.get('evaluation_status') == 'completed' and g.get('primary_sha256') and
            g.get('primary_sha256') == selected.get('primary_sha256') and
            g.get('review_id') == selected.get('review_id') for g in grades)
        status = ('completed' if complete else 'historical_unverified' if reported_complete else 'incomplete') if final else (
            'running' if running else 'interrupted' if running is False else
            'launch_failed' if request.get('returncode') is not None else 'unknown')
        rounds = team.get('rounds', {})
        reviews = evidence.get('reviews', [])
        counts = {'papers': len(evidence.get('papers', {})), 'cards': len(evidence.get('cards', {})),
            'searches': len(evidence.get('searches', [])),
            'proposals': len(team.get('proposals', {})),
            'candidates': sum(len(p.get('document', {}).get('candidates', [])) for p in team.get('proposals', {}).values()),
            'peer_reviews': sum(len(r.get('reviews', {})) for r in rounds.values()),
            'revisions': sum(len(r.get('revisions', {})) for r in rounds.values()),
            'syntheses': len(team.get('syntheses', [])),
            'advisories': sum(r.get('grading') is False for r in reviews),
            'formal_attempts': evidence.get('formal_attempts_used', result.get('formal_attempts_used', 0)),
            'formal_completed': sum(g.get('evaluation_status') == 'completed' for g in grades),
            'tools': evidence.get('tool_calls', 0)}
        stage = 'discovery'
        for key, name in (('proposals', 'proposals'), ('peer_reviews', 'discussion'),
                          ('syntheses', 'synthesis'), ('advisories', 'review'),
                          ('formal_attempts', 'grading')):
            if counts[key]:
                stage = name
        if stage == 'review' and not counts['syntheses']:
            stage = 'discussion' if counts['peer_reviews'] else 'proposals' if counts['proposals'] else 'discovery'
        if final and complete:
            stage = 'export'
        files = []
        for name in ARTIFACTS:
            p = run / name
            if p.is_file() and not p.is_symlink():
                files.append({'name': name, 'bytes': p.stat().st_size})
        return {'id': ident, 'topic': launch.get('topic', request.get('topic', '')),
            'started': launch.get('started', request.get('started')),
            'finished': result.get('finished'), 'status': status, 'stage': stage,
            'launcher_alive': running, 'counts': counts, 'budgets': launch.get('budgets', request.get('budgets', {})),
            'model': launch.get('model_configuration', {}).get('native_researcher', {}).get('model', 'unknown'),
            'researchers': launch.get('researchers', request.get('researchers')),
            'discussion_rounds': launch.get('discussion_rounds', request.get('discussion_rounds')),
            'snapshot_time': utcnow(),
            'snapshot_errors': {k: v for k, v in [('launch', launch_error), ('evidence', evidence_error),
                                                 ('team', team_error), ('result', result_error)] if v},
            'artifacts': files, 'independent_acceptance': False, 'experiments': 'not_covered',
            'workflow_status': result.get('workflow_status', 'not_finished'),
            'source_unchanged': result.get('framework_unchanged_during_run'),
            'exit_code': child.poll() if child else request.get('returncode')}

    def section(self, ident, section):
        run = self.path(ident)
        if section == 'summary':
            return self.summary(ident)
        evidence, ee = self.read(run / 'service-private' / 'evidence.json')
        team, te = self.read(run / 'service-private' / 'team-state.json')
        if section == 'input':
            launch, error = self.read(run / 'launch.json')
            return {'data': {k: v for k, v in launch.items() if k != 'framework_files'}, 'error': error}
        if section in ('candidates', 'overview'):
            final, error = self.read(run / 'conjectures.json')
            return {'data': {'exported': final, 'export_error': error,
                'syntheses': team.get('syntheses', []), 'proposals': team.get('proposals', {})}, 'error': te}
        if section == 'evidence':
            return {'data': {k: evidence.get(k, {}) for k in ('papers', 'cards')}, 'error': ee}
        if section == 'discussion':
            return {'data': {'rounds': team.get('rounds', {}),
                'peer_advice_audits': evidence.get('peer_advice_audits', {})}, 'error': te or ee}
        if section == 'reviews':
            return {'data': {'reviews': evidence.get('reviews', []), 'grades': evidence.get('grades', [])}, 'error': ee}
        if section == 'result':
            result, error = self.read(run / 'result.json')
            return {'data': result, 'error': error}
        if section == 'events':
            rows = []
            # A bounded tail, explicitly marked; never expose raw sessions/reasoning/env.
            path = run / 'service-private' / 'events.jsonl'
            if path.is_file() and not path.is_symlink():
                with path.open('rb') as handle:
                    size = path.stat().st_size
                    offset = max(0, size - 2 * 1024 * 1024)
                    handle.seek(offset)
                    if offset:
                        handle.readline()
                    for line in handle:
                        try:
                            e = json.loads(line)
                        except (ValueError, UnicodeError):
                            continue
                        keys = ('time', 'kind', 'tool', 'research_slot', 'event_sequence', 'request_id',
                                'input_sha256', 'output_sha256', 'wire_json_sha256', 'wire_json_bytes',
                                'output_bytes', 'elapsed_seconds', 'lineage', 'message', 'error', 'stage',
                                'validation_error', 'request_file')
                        rows.append({k: e[k] for k in keys if k in e})
            return {'data': rows[-200:], 'tail_only': True, 'limit': 200}
        raise ValueError('Unknown section')

    def artifact(self, ident, name):
        if name not in ARTIFACTS:
            raise ValueError('Artifact is not public')
        p = self.path(ident) / name
        if any(x.is_symlink() for x in (p, *p.parents)) or not p.is_file() or p.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Artifact unavailable')
        return p.read_bytes()

    def start(self, args):
        if not self.allow_live or args.get('allow_live') is not True:
            raise ValueError('Live start requires server --allow-live and explicit request opt-in')
        topic = args.get('topic')
        if not isinstance(topic, str) or not 1 <= len(topic.strip()) <= 20000:
            raise ValueError('Topic must contain 1..20000 characters')
        limits = {'researchers': (4, 1, 4), 'discussion_rounds': (2, 1, 3),
                  'max_attempts': (4, 1, 4), 'max_tools': (640, 1, 640), 'wall_seconds': (7200, 60, 7200)}
        config = {}
        for key, (default, low, high) in limits.items():
            value = args.get(key, default)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{key} must be an integer in {low}..{high}')
            config[key] = value
        with self.lock:
            for ident in self.run_ids():
                if self.summary(ident)['launcher_alive'] is True:
                    raise ValueError('An autonomous run is already active: ' + ident)
            # Catch manually started launchers before their launch.json exists.
            if Path('/proc').is_dir():
                for entry in Path('/proc').iterdir():
                    if entry.name.isdigit():
                        try:
                            argv = (entry / 'cmdline').read_bytes().split(b'\0')
                            if b'sage' in argv and b'autonomous' in argv:
                                raise ValueError('An autonomous launcher already exists; inspect it before starting')
                        except (FileNotFoundError, PermissionError, ProcessLookupError):
                            pass
            self.control.mkdir(parents=True, exist_ok=True, mode=0o700)
            ident = 'console-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3)
            command = [sys.executable, '-u', '-X', 'faulthandler', '-m', 'sage', 'autonomous', '--allow-live',
                       '--topic', topic.strip(), '--output', str(self.projects / ident)]
            for key, value in config.items():
                command += ['--' + key.replace('_', '-'), str(value)]
            record = {'id': ident, 'topic': topic.strip(), 'started': utcnow(), **config,
                      'budgets': config, 'returncode': None}
            atomic_json(self.control / (ident + '.json'), record)
            try:
                with (self.control / (ident + '.log')).open('xb') as log:
                    process = subprocess.Popen(command, cwd=self.repo, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name == 'posix')
            except OSError as exc:
                record.update(returncode=-1, launch_error=type(exc).__name__)
                atomic_json(self.control / (ident + '.json'), record)
                raise ValueError('Launcher could not start') from exc
            self.children[ident] = process
            def reap():
                code = process.wait()
                with self.lock:
                    record.update(returncode=code, exited=utcnow())
                    atomic_json(self.control / (ident + '.json'), record)
            threading.Thread(target=reap, daemon=True).start()
            return {'id': ident, 'pid': process.pid, 'status': 'starting'}


def handler_class(store, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Tokens and user inputs never enter an access log.

        def send(self, data, status=200, content_type='application/json; charset=utf-8'):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            host = self.headers.get('Host', '')
            if not re.fullmatch(r'(127\.0\.0\.1|localhost)(:\d+)?', host):
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + host:
                return False
            return hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path in ('/', '/app.js', '/style.css', '/planner.js', '/planner-ui.js', '/planner.css'):
                name, content_type = {'/': ('index.html', 'text/html; charset=utf-8'),
                    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                    '/planner.js': ('planner.js', 'text/javascript; charset=utf-8'),
                    '/planner.css': ('planner.css', 'text/css; charset=utf-8'),
                    '/planner-ui.js': ('planner-ui.js', 'text/javascript; charset=utf-8'),
                    '/style.css': ('style.css', 'text/css; charset=utf-8')}[parsed.path]
                return self.send((STATIC / name).read_bytes(), content_type=content_type)
            if not self.authorized():
                return self.send({'error': 'Unauthorized'}, 401)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == '/api/runs':
                    return self.send({'runs': [store.summary(i) for i in store.run_ids()], 'allow_live': store.allow_live})
                ident = query.get('id', [''])[0]
                if parsed.path == '/api/run':
                    return self.send(store.section(ident, query.get('section', ['summary'])[0]))
                if parsed.path == '/api/artifact':
                    data = store.artifact(ident, query.get('name', [''])[0])
                    return self.send(data, content_type='application/octet-stream')
                return self.send({'error': 'Not found'}, 404)
            except (ValueError, OSError) as exc:
                return self.send({'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}, 400)

        def do_POST(self):
            if not self.authorized():
                return self.send({'error': 'Unauthorized'}, 401)
            if self.path != '/api/runs':
                return self.send({'error': 'Not found'}, 404)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 100000:
                    raise ValueError('Invalid request length')
                args = json.loads(self.rfile.read(size))
                if not isinstance(args, dict):
                    raise ValueError('Request must be an object')
                return self.send(store.start(args), 201)
            except (ValueError, OSError) as exc:
                return self.send({'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}, 400)
    return Handler


def serve(args):
    token = os.environ.get('SAGE_CONSOLE_TOKEN') or secrets.token_urlsafe(32)
    if len(token) < 32:
        raise ValueError('SAGE_CONSOLE_TOKEN must contain at least 32 characters')
    store = RunStore(args.projects, allow_live=args.allow_live)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_class(store, token))
    print(f'SAGE console: http://127.0.0.1:{server.server_port}/#token={token}', flush=True)
    print('Loopback only. Use an SSH tunnel. Live start: ' + str(args.allow_live), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
