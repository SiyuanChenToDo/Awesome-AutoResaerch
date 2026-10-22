"""Resume native DSH sessions through CORAL's public custom-runtime interface.

Lifecycle integration is adapted from CORAL's DeepSeekHarnessRuntime at
0123dfb939b35228cf2c1fde224cd0561e727408 (Apache-2.0; see NOTICE.md).
Modified for SAGE: native --json/--session-id, private exact-session recovery,
strict startup acknowledgement and metadata-only public logs. Upstream stays
unmodified. A lightweight supervisor parks completed team workers without model
polling; native DSH remains responsible for restoring messages and tools.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from urllib.request import Request, urlopen

from ..artifacts import atomic_json, atomic_text

logger = logging.getLogger(__name__)
_SESSION = re.compile(r'session-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
_OPTIONS = {'command', 'profile', 'patch', 'provider', 'permission_mode',
            'tools_mode', 'session_state_dir', 'research_slot', 'research_team_size',
            'lifecycle_timeout_seconds', 'lifecycle_poll_seconds'}

RESTART_LEDGER_SCHEMA = 'sage.native_restart_ledger.v1'
RESTART_ESCAPE_RECEIPT_SCHEMA = 'sage.native_restart_escape.v1'
SESSION_ROTATION_RECEIPT_SCHEMA = 'sage.native_session_rotation.v1'
RESTART_LEDGER_HISTORY_LIMIT = 50
# Consecutive unproductive restarts (no_result / session_error /
# session_context_overflow) before the ledger archives the recorded session
# and start() opens a fresh native session instead of resuming the broken one.
RESTART_ESCAPE_FAILURES = 3
# Fresh sessions a single agent may open before the terminal policy fires.
FRESH_SESSION_LIMIT = 2
# Exact provider phrases from the native DSH stderr on context exhaustion.
_CONTEXT_OVERFLOW_MARKERS = ('maximum context length is 1048576', 'context_window_exceeded')
_ERR_READ_LIMIT = 262144


def supervised_argv(argv, slot, options, *, environ=None, now=None):
    """Only worker processes park; the coordinator keeps CORAL's normal flow."""
    if slot in (None, 0):
        return argv
    import math
    environ = os.environ if environ is None else environ
    seconds = float(options.get('lifecycle_timeout_seconds', 7200))
    poll = float(options.get('lifecycle_poll_seconds', 20))
    deadline = float(environ.get('SAGE_RUNTIME_DEADLINE_UNIX',
                                (time.time() if now is None else now) + seconds))
    if not all(math.isfinite(x) for x in (seconds, poll, deadline)) or seconds <= 0 or not 0 < poll <= 60:
        raise ValueError('Lifecycle timing must be finite, positive and bounded')
    return [sys.executable, '-m', 'sage.autonomous.lifecycle', '--slot', str(slot),
            '--deadline', str(deadline), '--poll-seconds', str(poll), '--', *argv]


def team_token(token, slot):
    return hmac.new(token.encode(), ('sage-research-slot:' + str(slot)).encode(), hashlib.sha256).hexdigest()


def register_researcher(slot, agent_id, cwd, session_id):
    """Manager-side registration from a validated native session event."""
    request = Request('http://127.0.0.1:' + os.environ['SAGE_RESEARCH_PORT'] + '/tool',
        data=json.dumps({'tool': 'runtime_register', 'arguments': {
            'slot': slot, 'agent_id': agent_id, 'cwd': str(cwd), 'session_id': session_id}}).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['SAGE_RESEARCH_TOKEN'],
                 'Content-Type': 'application/json'})
    with urlopen(request, timeout=30) as response:
        value = json.load(response)
    if value.get('error'):
        raise ValueError('Manager refused the native researcher identity')


def checked_id(value):
    # The pinned native headless creates session-${randomUUID()}. Never parse
    # identifiers from assistant prose or select the most recently modified file.
    if not isinstance(value, str) or not _SESSION.fullmatch(value):
        raise ValueError('Invalid native DSH session identifier')
    return value


def native_argv(command, *, profile='headless', patches=(), prompt='', resume_session_id=None):
    # --patch belongs to the outer launcher; --json starts headless's own
    # argument parser, so global patches MUST come before that boundary.
    argv = [str(command), '--profile', str(profile)]
    for patch in patches:
        argv.extend(['--patch', str(patch)])
    argv.append('--json')
    if resume_session_id is not None:
        argv.extend(['--session-id', checked_id(resume_session_id)])
    # Protect continuation prompts beginning with '-' from CLI interpretation.
    return argv + ['--', prompt]


def public_event(event):
    """Project native NDJSON to metadata; never export reasoning or tool data."""
    if not isinstance(event, dict) or event.get('type') == 'thinking':
        return None
    kind = event.get('type')
    if kind == 'sage_lifecycle':
        if (event.get('state') not in {'parked', 'waiting', 'resuming', 'stopped',
                                      'deadline', 'status_unavailable', 'native_error'}
                or type(event.get('slot')) is not int or not 1 <= event['slot'] <= 3):
            return None
        result = {'type': kind, 'state': event['state'], 'slot': event['slot']}
        if 'sessionId' in event:
            result['sessionId'] = checked_id(event['sessionId'])
        return result
    if not isinstance(kind, str) or kind not in {
            'session', 'status', 'text', 'tool_call', 'tool_result', 'final', 'error'}:
        return None
    if kind == 'session':
        if not isinstance(event.get('cwd'), str):
            raise ValueError('Native DSH session event has no working directory')
        return {'type': kind, 'sessionId': checked_id(event.get('sessionId')), 'cwd': event['cwd']}
    out = {'type': kind}
    if kind in {'text', 'final'}:
        out['text_characters'] = len(event.get('text', '')) if isinstance(event.get('text', ''), str) else 0
    return out


def session_from_log(path):
    path = Path(path)
    if not path.is_file():
        return None
    found, pending, rotation_count = None, None, 0
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get('type') == 'sage_session_rotation':
                # Only the manager writes this event, after checking its private
                # rotation receipt. public_event never accepts it from a worker.
                target = checked_id(event.get('sessionId'))
                count = event.get('rotated_session_count')
                if (pending is not None or found is None or event.get('archived_session_id') != found
                        or target == found or type(count) is not int or count <= rotation_count):
                    raise ValueError('Invalid native session rotation chain')
                pending, rotation_count = target, count
            elif isinstance(event, dict) and event.get('type') == 'session':
                current = checked_id(event.get('sessionId'))
                if (pending is not None and current != pending) or (
                        pending is None and found is not None and current != found):
                    raise ValueError('Conflicting native session identifiers in one launch')
                found, pending = current, None
    return found


def state_path(worktree_path, state_root):
    cwd = str(Path(worktree_path).resolve())
    return Path(state_root) / (hashlib.sha256(cwd.encode()).hexdigest() + '.json')


def private_state_root(worktree_path, state_root):
    root = Path(state_root).absolute()
    if root.is_symlink() or root.parent.is_symlink() or root.resolve().is_relative_to(Path(worktree_path).resolve()):
        raise ValueError('Session state must be a manager-owned directory outside the agent worktree')
    if os.name == 'posix':
        parent = root.parent.stat()
        if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
            raise ValueError('Session state parent can be modified by another account')
        if root.exists() and (root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077):
            raise ValueError('Existing session state is not manager-private')
    return root


def saved_session(worktree_path, agent_id, *, state_root):
    path = state_path(worktree_path, private_state_root(worktree_path, state_root))
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError('Session pointer cannot be a symlink')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('cwd') != str(Path(worktree_path).resolve())
                or value.get('agent_id') != agent_id):
            raise ValueError('Session pointer does not belong to this agent and worktree')
        return checked_id(value.get('session_id'))
    except (OSError, ValueError) as exc:
        raise ValueError('Cannot restore the recorded native session; refusing a fresh fallback') from exc


def save_session(worktree_path, agent_id, session_id, *, state_root, native_process=None):
    checked_id(session_id)
    state_root = private_state_root(worktree_path, state_root)
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_root.chmod(0o700)
    atomic_json(state_path(worktree_path, state_root), {
        'schema_version': 'sage.native_session.v1', 'agent_id': agent_id,
        'cwd': str(Path(worktree_path).resolve()), 'session_id': checked_id(session_id),
        **({'native_process': native_process} if native_process is not None else {})})


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def restart_ledger_path(state_root, agent_id):
    return Path(state_root) / (agent_id + '.restart-ledger.json')


def fresh_restart_ledger(worktree_path, agent_id):
    return {'schema_version': RESTART_LEDGER_SCHEMA, 'agent_id': agent_id,
            'cwd': str(Path(worktree_path).resolve()), 'current_session_id': None,
            'consecutive_failures': 0, 'fresh_session_count': 0,
            'rotated_session_count': 0,
            'history': [], 'updated_at': None}


def load_restart_ledger(worktree_path, agent_id, *, state_root):
    """Manager-private per-agent restart ledger; corrupt or foreign JSON starts over."""
    root = private_state_root(worktree_path, state_root)
    default = fresh_restart_ledger(worktree_path, agent_id)
    try:
        raw = json.loads(restart_ledger_path(root, agent_id).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default
    if (not isinstance(raw, dict) or raw.get('schema_version') != RESTART_LEDGER_SCHEMA
            or raw.get('agent_id') != agent_id or raw.get('cwd') != default['cwd']):
        return default
    ledger = dict(default)
    for key in default:
        if key in raw:
            ledger[key] = raw[key]
    if not isinstance(ledger['history'], list):
        ledger['history'] = []
    ledger['history'] = [entry for entry in ledger['history']
                         if isinstance(entry, dict)][-RESTART_LEDGER_HISTORY_LIMIT:]
    for key in ('consecutive_failures', 'fresh_session_count', 'rotated_session_count'):
        if type(ledger[key]) is not int or ledger[key] < 0:
            ledger[key] = 0
    if ledger['current_session_id'] is not None:
        try:
            checked_id(ledger['current_session_id'])
        except ValueError:
            ledger['current_session_id'] = None
    return ledger


def save_restart_ledger(worktree_path, agent_id, *, state_root, ledger):
    root = private_state_root(worktree_path, state_root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == 'posix':
        root.chmod(0o700)
    ledger['history'] = ledger['history'][-RESTART_LEDGER_HISTORY_LIMIT:]
    ledger['updated_at'] = _utc_now()
    atomic_json(restart_ledger_path(root, agent_id), ledger)


def _delete_session_pointer(worktree_path, state_root):
    """Drop the private saved_session pointer; missing is already the goal."""
    try:
        state_path(worktree_path, state_root).unlink()
    except FileNotFoundError:
        pass


def plan_restart(worktree_path, agent_id, state_root, *, resume_session_id=None,
                 prompt_source=None, slot=None):
    """Resolve the resume decision with the restart-ledger escape and terminal policy.

    CORAL restarts a dead agent with the session id extracted from its old log,
    which after a context-overflow crash resumes the exact broken session on
    every restart. The ledger counts consecutive unproductive exits; once the
    escape threshold is reached this archives the session, deletes the private
    pointer, and starts a fresh native session instead of resuming.

    Raises RuntimeError under the terminal policy (fresh sessions exhausted and
    the current session still fails): letting that escape propagate terminates
    the CORAL manager and ends the whole run, which is the approved terminal
    strategy — an agent whose every session dies the same way must not burn
    budget on ~861-token eval feedback injections per restart.
    """
    state_root = private_state_root(worktree_path, state_root)
    previous = saved_session(worktree_path, agent_id, state_root=state_root)
    ledger = load_restart_ledger(worktree_path, agent_id, state_root=state_root)
    ledger_path = restart_ledger_path(state_root, agent_id)
    fresh_reset, archived = False, None
    if ledger['consecutive_failures'] >= RESTART_ESCAPE_FAILURES:
        if ledger['fresh_session_count'] >= FRESH_SESSION_LIMIT:
            recent = '; '.join(
                f"{entry.get('recorded_at', '?')}:{entry.get('classification') or entry.get('event')}"
                for entry in ledger['history'][-RESTART_ESCAPE_FAILURES * 2:])
            raise RuntimeError(
                f'Native researcher {agent_id}' +
                (f' (research slot {slot})' if slot is not None else '') +
                f' exhausted session recovery: {ledger["fresh_session_count"]} fresh sessions were '
                f'already opened, and the current session still failed {ledger["consecutive_failures"]} '
                f'consecutive restarts. Restart ledger: {ledger_path}. Recent history: {recent}. '
                'Workspace files are intact; human inspection is required.')
        archived = ledger['current_session_id'] or previous
        prior_failures = ledger['consecutive_failures']
        ledger['fresh_session_count'] += 1
        ledger['consecutive_failures'] = 0
        ledger['current_session_id'] = None
        ledger['history'].append({'event': 'session_archived', 'recorded_at': _utc_now(),
            'archived_session_id': archived, 'prior_consecutive_failures': prior_failures,
            'reason': (f'{prior_failures} consecutive unproductive restarts; the recorded session '
                       'cannot make progress (context window exhausted). Workspace files are intact.')})
        save_restart_ledger(worktree_path, agent_id, state_root=state_root, ledger=ledger)
        # Escape receipt beside the ledger: manager-private evidence, never in the worktree.
        atomic_json(state_root / (agent_id + '.restart-escape.json'), {
            'schema_version': RESTART_ESCAPE_RECEIPT_SCHEMA, 'agent_id': agent_id,
            'worktree': str(Path(worktree_path).resolve()), 'archived_session_id': archived,
            'prior_consecutive_failures': prior_failures,
            'fresh_session_count': ledger['fresh_session_count'],
            'prompt_source': prompt_source, 'ledger_path': str(ledger_path),
            'recorded_at': _utc_now()})
        _delete_session_pointer(worktree_path, state_root)
        # The condemned session must not resurface through the stale local copy.
        previous = None
        fresh_reset = True
    rotated_ids = {entry.get('archived_session_id') for entry in ledger['history']
                   if entry.get('event') == 'session_rotated'
                   and isinstance(entry.get('archived_session_id'), str)}
    rotation_reset = False
    resolved = resume_session_id
    if resolved is not None:
        checked_id(resolved)
        if fresh_reset:
            # The ledger condemned this exact session; a requested resume id
            # extracted from the dead agent's log must not resurrect it.
            resolved = None
        elif previous is None and resolved in rotated_ids:
            # Crash between a phase-barrier rotation and the fresh session's
            # first recorded save: a stale log extraction must not resurrect
            # the rotated session, and the continuation guard below must not
            # block the replacement fresh start either.
            resolved = None
            rotation_reset = True
        elif previous is not None and previous != resolved:
            raise ValueError('Requested session differs from the exact recorded native session')
    elif previous is not None:
        resolved = previous
    elif rotated_ids:
        # A rotation archived the only recorded session and no replacement id
        # was requested or could be extracted from the log: the fresh
        # continuation must not hit the refused-fresh guard below.
        rotation_reset = True
    elif not fresh_reset and prompt_source in {'resume', 'restart', 'reflect', 'pivot'}:
        raise ValueError('Continuation has no native session identity; refusing to start fresh')
    return {'state_root': state_root, 'previous_session_id': previous, 'resume_session_id': resolved,
            'fresh_reset': fresh_reset, 'rotation_reset': rotation_reset, 'archived_session_id': archived,
            'fresh_session_count': ledger['fresh_session_count'], 'ledger': ledger,
            'ledger_path': ledger_path}


def rotate_session(worktree_path, agent_id, state_root, *, reason):
    """Manager-driven phase-barrier session rotation (AgentLab-style).

    This is the routine counterpart of plan_restart's failure escape: the team
    manager archives the current native session at a phase barrier so the next
    launch starts a fresh session and the agent continues from its externalized
    wiki/notes instead of a linearly grown transcript. The bookkeeping reuses
    the restart-ledger machinery, but a rotation never touches
    consecutive_failures and is not bounded by RESTART_ESCAPE_FAILURES or
    FRESH_SESSION_LIMIT; it is recorded separately in rotated_session_count
    and in a manager-private receipt beside the ledger. ``reason`` names the
    team phase barrier (for example ``review:r1`` or ``synthesize``).
    """
    state_root = private_state_root(worktree_path, state_root)
    previous = saved_session(worktree_path, agent_id, state_root=state_root)
    ledger = load_restart_ledger(worktree_path, agent_id, state_root=state_root)
    ledger_path = restart_ledger_path(state_root, agent_id)
    # The pointer tracks the live session; the exit ledger may describe the
    # session from a previous launch until this launch exits.
    archived = previous or ledger['current_session_id']
    ledger['rotated_session_count'] += 1
    ledger['current_session_id'] = None
    ledger['history'].append({'event': 'session_rotated', 'recorded_at': _utc_now(),
        'archived_session_id': archived, 'reason': reason})
    save_restart_ledger(worktree_path, agent_id, state_root=state_root, ledger=ledger)
    atomic_json(state_root / (agent_id + '.session-rotation.json'), {
        'schema_version': SESSION_ROTATION_RECEIPT_SCHEMA, 'agent_id': agent_id,
        'worktree': str(Path(worktree_path).resolve()), 'archived_session_id': archived,
        'reason': reason, 'rotated_session_count': ledger['rotated_session_count'],
        'consecutive_failures': ledger['consecutive_failures'], 'ledger_path': str(ledger_path),
        'recorded_at': _utc_now()})
    _delete_session_pointer(worktree_path, state_root)
    return {'state_root': state_root, 'archived_session_id': archived, 'reason': reason,
            'rotated_session_count': ledger['rotated_session_count'], 'ledger': ledger,
            'ledger_path': ledger_path}


def accept_session_event(event, *, worktree, agent_id, state_root, previous,
                         initial_resume, rotation_count, slot, native_process=None):
    """Bind a native session, permitting only a manager-authorized phase rotation."""
    native_id = checked_id(event.get('sessionId'))
    if Path(event['cwd']).resolve() != Path(worktree).resolve():
        raise ValueError('Native DSH resumed an unexpected worktree')
    transition = None
    if previous is None:
        if initial_resume is not None and native_id != initial_resume:
            raise ValueError('Native DSH resumed an unexpected session')
    elif previous != native_id:
        root = private_state_root(worktree, state_root)
        receipt_path = root / (agent_id + '.session-rotation.json')
        if slot not in (1, 2, 3) or receipt_path.is_symlink():
            raise ValueError('Native session change has no authorized worker rotation')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        ledger = load_restart_ledger(worktree, agent_id, state_root=root)
        count = receipt.get('rotated_session_count')
        history = ledger['history']
        last = history[-1] if history else {}
        if (receipt.get('schema_version') != SESSION_ROTATION_RECEIPT_SCHEMA
                or receipt.get('agent_id') != agent_id
                or receipt.get('worktree') != str(Path(worktree).resolve())
                or receipt.get('archived_session_id') != previous
                or type(count) is not int or count <= rotation_count
                or count != ledger['rotated_session_count']
                or ledger['current_session_id'] is not None
                or state_path(worktree, root).exists()
                or last.get('event') != 'session_rotated'
                or last.get('archived_session_id') != previous
                or last.get('reason') != receipt.get('reason')
                or any(item.get('archived_session_id') == native_id for item in history)):
            raise ValueError('Native session change does not match the private rotation receipt')
        rotation_count = count
        transition = {'type': 'sage_session_rotation', 'archived_session_id': previous,
                      'sessionId': native_id, 'rotated_session_count': count}
    save_session(worktree, agent_id, native_id, state_root=state_root, native_process=native_process)
    if slot is not None and previous != native_id:
        register_researcher(slot, agent_id, worktree, native_id)
    return rotation_count, transition


class ResumableDeepSeekRuntime:
    instruction_filename = 'AGENTS.md'
    shared_dir_name = '.dsh'

    def extract_session_id(self, log_path):
        return session_from_log(log_path)

    def classify_exit(self, log_path, exit_code, uptime_seconds, min_clean_runtime_seconds=60):
        # The native final event makes short, successful tasks distinguishable
        # from startup crashes; no stdout-duration guess is needed.
        try:
            events = [json.loads(line) for line in Path(log_path).read_text(encoding='utf-8').splitlines()
                      if line.startswith('{')]
        except (OSError, ValueError):
            classification = 'no_result'
        else:
            if any(isinstance(e, dict) and e.get('type') == 'sage_runtime_error' for e in events):
                classification = 'session_error'
            else:
                classification = 'clean' if exit_code == 0 and any(
                    isinstance(e, dict) and e.get('type') == 'final' for e in events) else 'no_result'
        return self._record_restart_ledger(Path(log_path), exit_code, classification)

    def _record_restart_ledger(self, log_path, exit_code, classification):
        """Book the exit into the per-agent ledger; overflow gets its own class.

        A context-window exhaustion is a no_result with a precise cause: the DSH
        provider writes it to the agent's stderr, so a no_result/session_error
        with the marker in this launch's stderr tail is reported as
        session_context_overflow (CORAL treats any non-clean class as a crash,
        so the new value stays wire-compatible with the manager). Bookkeeping
        must never raise: CORAL falls back to an uptime heuristic otherwise.
        """
        scope = getattr(self, '_restart_scope', None)
        if not isinstance(scope, dict) or Path(log_path).parent != scope.get('log_dir'):
            return classification
        try:
            if classification != 'clean':
                # agent.err accumulates across restarts (append mode); only the
                # bytes written during this launch may classify an overflow.
                try:
                    with open(scope['err_path'], 'rb') as stream:
                        stream.seek(scope.get('err_offset') or 0)
                        tail = stream.read(_ERR_READ_LIMIT).decode('utf-8', errors='replace').casefold()
                except OSError:
                    tail = ''
                if any(marker in tail for marker in _CONTEXT_OVERFLOW_MARKERS):
                    classification = 'session_context_overflow'
            try:
                session_id = session_from_log(log_path)
            except ValueError:
                session_id = None
            ledger = load_restart_ledger(scope['worktree'], scope['agent_id'],
                                         state_root=scope['state_root'])
            ledger['history'].append({'event': 'exit', 'recorded_at': _utc_now(),
                'classification': classification, 'exit_code': exit_code,
                'session_id': session_id})
            if session_id is not None:
                ledger['current_session_id'] = session_id
            # A clean exit proves the session is alive again: reset the failure
            # run. fresh_session_count stays — it records how many sessions the
            # agent has already burned.
            ledger['consecutive_failures'] = (0 if classification == 'clean'
                                              else ledger['consecutive_failures'] + 1)
            save_restart_ledger(scope['worktree'], scope['agent_id'],
                                state_root=scope['state_root'], ledger=ledger)
        except Exception:
            logger.warning('Restart ledger bookkeeping failed for %s',
                           scope.get('agent_id'), exc_info=True)
        return classification

    def start(self, worktree_path, coral_md_path, model='deepseek-flash', runtime_options=None,
              max_turns=0, log_dir=None, verbose=False, resume_session_id=None, prompt=None,
              prompt_source=None, task_name=None, task_description=None, gateway_url=None,
              gateway_api_key=None, run_as_user=None, sandbox=None):
        # Optional CORAL dependency stays lazy so offline SAGE needs no install.
        from coral.agent.runtime import (AgentHandle, apply_run_as_user, apply_sandbox,
                                         apply_sandbox_env, write_coral_log_entry)
        from coral.agent.process import open_agent_stderr_for_log_dir
        from coral.venv_paths import venv_bin_dir
        from coral.workspace.repo import _clean_env

        worktree_path = Path(worktree_path).resolve()
        agent_id = (worktree_path / '.coral_agent_id').read_text(encoding='utf-8').strip()
        opts = dict(runtime_options or {})
        if set(opts) - _OPTIONS or not opts.get('session_state_dir'):
            raise ValueError('Resumable DSH needs an explicit private session_state_dir and supported options')
        plan = plan_restart(worktree_path, agent_id, opts['session_state_dir'],
                            resume_session_id=resume_session_id, prompt_source=prompt_source,
                            slot=opts.get('research_slot'))
        state_root = plan['state_root']
        resume_session_id = plan['resume_session_id']
        if plan['fresh_reset']:
            logger.warning('Restart ledger for %s archived session %s after %s consecutive '
                           'unproductive restarts; opening fresh session #%s', agent_id,
                           plan['archived_session_id'], RESTART_ESCAPE_FAILURES,
                           plan['fresh_session_count'])
        elif plan['rotation_reset']:
            logger.warning('Restart ledger for %s refused to resurrect rotated session; '
                           'opening a fresh session instead', agent_id)
        elif plan['previous_session_id'] is not None:
            # CORAL's generic whole-manager validator recognizes Claude files
            # only. Recover our exact private pointer, never a guessed latest log.
            logger.info('Restoring recorded native DSH session %s for %s',
                        plan['previous_session_id'], agent_id)
        if prompt is None:
            prompt = ('Continue the existing research session and address the current feedback.'
                      if resume_session_id else 'Begin working on your task and iterating on the seed solution.')
        if plan['fresh_reset']:
            archived = plan['archived_session_id']
            where = (f'Previous native session {archived} was archived'
                     if archived else 'The previous native session was archived')
            prompt += (f'\n\n[runtime status] {where} after {RESTART_ESCAPE_FAILURES} consecutive '
                       'unproductive restarts (context window exhausted); workspace files are '
                       f'intact. This is fresh session #{plan["fresh_session_count"]} for this agent.')
        elif plan['rotation_reset']:
            prompt += ('\n\n[runtime status] The previous phase session was rotated away at a '
                       'team phase barrier and must not be resumed; workspace files are intact. '
                       'This fresh session continues from your wiki and shared notes.')
        slot = opts.get('research_slot')
        if slot is not None:
            size = opts.get('research_team_size')
            if type(slot) is not int or type(size) is not int or not 0 <= slot < size <= 4:
                raise ValueError('Invalid research team assignment')
            prompt = (f'Your authenticated research team slot is {slot}, native agent {agent_id}. '
                      'Call the research team tool with action=status first for your role and required action. '
                      'Follow the team protocol in the supplied instructions. Only slot 0 submits coral eval.\n\n' + prompt)

        dsh_home = worktree_path / '.dsh'
        dsh_home.mkdir(exist_ok=True)
        # Never write as root into .dsh: CORAL makes that tree agent-owned.
        # A hostile symlink there must not redirect a later manager write.
        config_root = state_root.parent / 'runtime-config'
        if config_root.is_symlink():
            raise ValueError('Runtime configuration directory cannot be a symlink')
        config_root.mkdir(mode=0o755, exist_ok=True)
        if os.name == 'posix' and (config_root.stat().st_uid != os.geteuid() or config_root.stat().st_mode & 0o022):
            raise ValueError('Runtime configuration directory is not manager-owned')
        config_root.chmod(0o755)
        model_patch = config_root / ('model-' + uuid.uuid4().hex + '.patch.yml')
        atomic_text(model_patch, '- id: agent-default-model\n  config:\n'
            f'    provider: {json.dumps(opts.get("provider", "deepseek-official"))}\n'
            f'    model: {json.dumps(model)}\n')
        model_patch.chmod(0o644)
        patches = opts.get('patch', [])
        if isinstance(patches, (str, Path)):
            patches = [patches]
        argv = native_argv(opts.get('command', 'dsh'), profile=opts.get('profile', 'headless'),
                           patches=[*patches, model_patch], prompt=prompt,
                           resume_session_id=resume_session_id)
        argv = supervised_argv(argv, slot, opts)
        env = _clean_env()
        env.update(DSH_HOME=str(dsh_home), UV_PROJECT_ENVIRONMENT=str(worktree_path / '.venv'),
                   VIRTUAL_ENV=str(worktree_path / '.venv'))
        if slot is not None:
            env['SAGE_RESEARCH_TOKEN'] = team_token(os.environ['SAGE_RESEARCH_TOKEN'], slot)
        env['PATH'] = str(venv_bin_dir(worktree_path / '.venv')) + os.pathsep + env.get('PATH', '')
        for option, variable in [('permission_mode', 'DSH_PERMISSION_MODE'), ('tools_mode', 'DSH_TOOLS_MODE')]:
            if opts.get(option):
                env[variable] = str(opts[option])
        if gateway_url:
            env['DEEPSEEK_BASE_URL'] = gateway_url
        if gateway_api_key:
            env['DEEPSEEK_API_KEY'] = gateway_api_key
        apply_sandbox_env(env, sandbox)
        user_kwargs = apply_run_as_user(env, run_as_user)
        if user_kwargs:
            user_kwargs['extra_groups'] = []
        from .lifecycle import acquire_owner_guard
        owner_guard = acquire_owner_guard(state_root.parent, user_kwargs.get('user', os.getuid()))
        log_dir = Path(log_dir) if log_dir else dsh_home / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f'{agent_id}.{len(list(log_dir.glob(f"{agent_id}*.log")))}.log'
        log_file = log_path.open('w', encoding='utf-8', buffering=1)
        write_coral_log_entry(log_file, prompt=prompt, source=prompt_source or ('resume' if resume_session_id else 'start'),
                             agent_id=agent_id, session_id=resume_session_id,
                             task_name=task_name, task_description=task_description)
        opened = open_agent_stderr_for_log_dir(log_dir, agent_id)
        err_path, err_file = opened if opened is not None else (log_path.with_suffix('.err'), None)
        if err_file is None:
            err_file = err_path.open('w', encoding='utf-8')
        try:
            err_offset = err_path.stat().st_size
        except OSError:
            err_offset = 0
        # classify_exit receives no state_root; stash exactly what the restart
        # ledger needs for this launch. One CORAL runtime instance serves one
        # agent_id, so the scope is unambiguous.
        self._restart_scope = {'agent_id': agent_id, 'worktree': worktree_path,
                               'state_root': state_root, 'ledger_path': plan['ledger_path'],
                               'log_dir': log_dir, 'err_path': err_path, 'err_offset': err_offset}
        try:
            process, native_process = owner_guard.launch(apply_sandbox(argv, sandbox),
                cwd=worktree_path, env=env, stdout=subprocess.PIPE, stderr=err_file,
                start_new_session=True, **user_kwargs)
        except BaseException:
            log_file.close()
            err_file.close()
            raise
        handle = AgentHandle(agent_id=agent_id, process=process, worktree_path=worktree_path,
                             log_path=log_path, err_file=err_file, err_path=err_path)
        ready = threading.Event()
        state = {'session_id': None, 'error': None,
                 'rotation_count': plan['ledger']['rotated_session_count']}

        def pump():
            try:
                for raw in process.stdout:
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        # Startup diagnostics cannot attest session identity.
                        # Retain their existence, never their arbitrary content.
                        log_file.write(json.dumps({'type': 'sage_native_diagnostic', 'bytes': len(raw)}) + '\n')
                        continue
                    projected = public_event(event)
                    if projected is None:
                        continue
                    if projected['type'] == 'session':
                        native_id = projected['sessionId']
                        state['rotation_count'], transition = accept_session_event(projected,
                            worktree=worktree_path, agent_id=agent_id, state_root=state_root,
                            previous=state['session_id'], initial_resume=resume_session_id,
                            rotation_count=state['rotation_count'], slot=slot, native_process=native_process)
                        if transition is not None:
                            log_file.write(json.dumps(transition) + '\n')
                        state['session_id'] = handle.session_id = native_id
                    elif state['session_id'] is None:
                        raise ValueError('Native DSH output arrived before its session identity')
                    log_file.write(json.dumps(projected, ensure_ascii=False) + '\n')
                    log_file.flush()
                    if state['session_id']:
                        ready.set()
            except Exception:
                # Keep error data and hidden reasoning out of the public log.
                state['error'] = 'Native session protocol failed; refusing a fresh fallback'
                log_file.write(json.dumps({'type': 'sage_runtime_error', 'error': state['error']}) + '\n')
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        process.terminate()
            finally:
                ready.set()
                log_file.close()

        threading.Thread(target=pump, daemon=True, name=f'dsh-{agent_id}-metadata').start()
        if not ready.wait(timeout=60) or state['error'] or not state['session_id']:
            handle.stop()
            raise RuntimeError('Native DSH did not acknowledge the expected persisted session; inspect private stderr')
        logger.info('Native DSH %s session %s for %s', 'resumed' if resume_session_id else 'created',
                    state['session_id'], agent_id)
        return handle
